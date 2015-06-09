#!/usr/bin/env python

import argparse # command line arguments (--password)

import time
import logging

import csv
import re
from functools import partial
#from getpass import getpass

import upsdata # separate code under upsdata directory
# settings in config.py
from config import (params, 
                    shipments_heading, pslips_heading, 
                    contacts_heading,  mail_fieldtags,
                    item_column_labels)

# for email functionality
import smtplib
import os.path
from email.MIMEMultipart import MIMEMultipart
from email.MIMEText import MIMEText
from email.Utils import formatdate


dlr_email_template = open(params['dlr_email_template_file']).read()
BigVendor_email_template = open(params['BigVendor_email_template_file']).read()

contacts_dtable = list(csv.DictReader(open(params['contacts_csv'], 'rU')))
shipments_dtable = list(csv.DictReader(open(params['shipments_csv'], 'rU')))
pslips_dtable = list(csv.DictReader(open(params['packingslips_csv'], 'rU')))


class Error(Exception):
    """Base class for exceptions in this module."""
    pass


class TableRecordNotFound(Error):
    """Exception raised for (...).
    Attributes:
        expr -- input expression in which the error occurred
        msg  -- explanation of the error
    """
    def __init__(self, msg1, msg2):
        self.msg1, self.msg2 = msg1, msg2

class ContactInfoMissing(Error):
    def __init__(self, msg):
        self.msg = msg



class PackedItem(object):
    def __init__(self, part_code, description, quantity):
        self.part_code = part_code
        self.description = description
        self.quantity = quantity

    def __repr__(self):
        template = "PackedItem object: code={0}, descr={1}, quant={2}"
        return template.format(self.part_code, self.description,
                               self.quantity)


class Notification(object):
    def __init__(self, slip_id):
        self.slip_id = int(slip_id)

        self.flag_template_incomplete = False 
        self.flag_no_email_address = False 
        self.flag_bad_tracking_number = False
        self.flag_no_greeting_name = False

        missing_value_text = params['text_placeholder_if_info_missing']

        slip_rows = [row for row in pslips_dtable 
                     if row[pslips_heading['slip_id']] == slip_id]

        # should always return at least one row
        try:
            slip_first = slip_rows[0]
        except IndexError:
            log("Attempted to look up a Slip ID that isn't in the slip list: %s" % slip_id)
            raise
        
        self.order_id = slip_first[pslips_heading['order_id']]

        # Look up UPS information using upsdata (in subfolder)
        tracknum = slip_first[pslips_heading['tracknum']]
        self.tracking_number = str(tracknum).upper().strip()
        try:
            self.expected_date = get_expected_date(self.tracking_number)
        except upsdata.TrackingNumberInvalid:
            log("Invalid tracking number: " + self.tracking_number)
            self.bad_tracking_number = True
            self.flag_template_incomplete = True
            self.expected_date = missing_value_text

        # record packed items, used to generate listing in email later
        self.items = [PackedItem(part_code=row[pslips_heading['partcode']],
                                 description=row[pslips_heading['description']],
                                 quantity=row[pslips_heading['quantity']])
                      for row in slip_rows]

        # for BigVendor customers: compare "Reference 4" to "ShortChar01" in shipments 
        #   to determine customer ID

        if slip_first[pslips_heading['cust_id']] == params['BigVendor_code']:

            self.is_BigVendor = True
            self.dns = slip_first[pslips_heading['BigVendor_dns_number']]

            # get "Reference 5" from packing slip: we'll use this to look up the Shipments
            # row that has this same value under "ShortChar01"
            shortchar_val = slip_first[pslips_heading['BigVendor_shortchar_id']]

            self.greeting_name = slip_first[pslips_heading['addr_name']]
            email_subject_line = params['email_subject_line_jd']
            try:
               self.customer_id = dtable_query(dtable=shipments_dtable,
                                               index_field=shipments_heading['BigVendor_shortchar_lookup'],
                                               index_id=shortchar_val,
                                               output_field=shipments_heading['cust_id'])
            except TableRecordNotFound as e:
                self.customer_id = missing_value_text
                self.flag_template_incomplete = True

        else: #non-BigVendor

            self.is_BigVendor = False
            self.dns = None
            self.customer_id = slip_first[pslips_heading['cust_id']]
            email_subject_line = params['email_subject_line_non_jd']
            try:
                self.greeting_name = dtable_query(dtable=shipments_dtable,
                                                index_field=shipments_heading['cust_id'],
                                                index_id=self.customer_id,
                                                output_field=shipments_heading['name'])
            except TableRecordNotFound as e:
                self.greeting_name = missing_value_text
                self.flag_template_incomplete = True
                self.flag_no_greeting_name = True

        if not self.flag_no_greeting_name:
            try:
                assert len(self.greeting_name) > 0
            except AssertionError as e:
                log('Email address record found for cust.id [%s] but name is blank'
                    % customer_id)
                self.flag_template_incomplete = True
                self.flag_no_greeting_name = True

        self.name_line = slip_first[pslips_heading['addr_name']]

        address_fields = [pslips_heading['addr_line1'],
                          pslips_heading['addr_line2'],
                          pslips_heading['addr_line3']]

        address_lines = [slip_first[f] for f in address_fields]

        address_lines_nonblank = filter(len, address_lines)
        self.address_html = '<br>'.join(address_lines_nonblank)

        #format final address line
        city = slip_first[pslips_heading['addr_city']]
        state = slip_first[pslips_heading['addr_state']]
        pcode = slip_first[pslips_heading['addr_pcode']]
        self.citysz_line = '{c}, {s} {p}'.format(c=city, s=state, p=pcode)

        try:
            self.contact_email = get_contact_email(self.customer_id)
        except ContactInfoMissing as e:
            self.contact_email = missing_value_text
            self.flag_no_email_address = True

        self.email_content = self.get_filled_template(replace_missing_with=missing_value_text)

        # used to produce issue notification email sent to company address if needed
        problems = ["<p>Customer email could not be sent:</p><ul>"]
            
        # Decide whether email can be sent to customer
        if all([not self.flag_template_incomplete, not self.flag_no_email_address,
                not self.flag_bad_tracking_number, not self.flag_no_greeting_name]):

            # flags indicate that nothing is missing: verify output text, then proceed
            try:
                assert missing_value_text not in self.email_content
                assert missing_value_text not in self.contact_email
            except AssertionError:
                problems.append("<li>Placeholder text was present in an email " 
                                "that wasn't flagged with missing data.</li>")

            # otherwise no problems: send it
            log("Attempting to send email to customer address: %s"
                % self.contact_email)

            if params['email_in_testing_mode']:
                actual_email_destination = params['test_email_recipient_as_customer']
                log("(but this is in testing mode, so actually sending to: %s" % 
                    actual_email_destination)
            else:
                actual_email_destination = self.contact_email

            result = send_gmail(gmail_username=params['gmail_userid'], 
                       gmail_pwd=params['gmail_password'],
                       send_from=params['email_from_name'], 
                       send_to=actual_email_destination, 
                       cc_to=params['email_address_for_company_records'],
                       subject=email_subject_line,
                       html_content=self.email_content, 
                       simulation_mode=params['simulated_emails'])
            log(result)

        else:
            # There is either a missing template value or a missing 
            # customer contact name/email
            if self.flag_template_incomplete:
                prob = "One or more values needed to fill the email template was missing."
                problems.append("<li>" + prob + "</li>")
                log(prob)
            if self.flag_no_email_address:
                prob = "Customer email address could not be found in Contacts CSV."
                problems.append("<li>" + prob + "</li>")
                log(prob)
            if self.flag_no_greeting_name:
                assert not self.is_BigVendor # packing slip should always have a customer name
                prob = ("For this non-JD order, customer name for email greeting could not be "
                       "pulled from the customer shipments CSV through a customer ID match.")
                problems.append("<li>" + prob + "</li>")
                log(prob)
            if self.flag_bad_tracking_number:
                prob = "Tracking number is missing or reported invalid by UPS API."
                problems.append("<li>" + prob + "</li>")
                log(prob)

            object_info = ['%s: %s' % (k, v) for k, v in vars(self).items()]
            notification_details = '<br><br>'.join(sorted(object_info))
            problems.append("</ul> <br><br> <b>Debugging info:</b> <br><br>\n" 
                            + notification_details)

            email_note = '\n'.join(problems)
            email_note_subject = ("Slip ID %s: could not send customer shipping "
                                  "notification" % self.slip_id)
            
            # Send detailed info in a notification email to internal address
            send_internal_email(subject=email_note_subject, 
                                content=email_note)

            # Send a clean copy of the shipping info (with missing info noted)
            # to the internal notification address
            send_internal_email(subject=("Incomplete notification for "
                                         "slip ID %s" % self.slip_id),
                                content=self.email_content)

        #when sending email

        #    raise


    def get_html_item_table(self):

        # table can be rearranged by changing the order of both the
        # heading names and the item attributes here

        heading_names = [item_column_labels['part'],
                         item_column_labels['description'],
                         item_column_labels['quantity']
                         ]

        values_arranged = [(item.part_code,
                            item.description,
                            item.quantity) for item in self.items]

        def cell(val): 
            return '<td>%s</td>' % val

        def row(value_tuple): 
            cells = ''.join([cell(val) for val in value_tuple])
            return ''.join(['<tr>', cells, '</tr>'])

        def grid(value_tuple_list):
            rows = [row(i) for i in value_tuple_list]
            return '\n\t'.join(rows)

        def table(heading_row, main_table):
            # not html5 standard, but still renders in current browsers
            table_outer_template = ('<table cellpadding="3" border="1">\n\t'
                                    '{}\n\t'
                                    '</table>')
            all_rows = '\n\t'.join([heading_row, main_table])
            return table_outer_template.format(all_rows)

        header = row(heading_names)
        main_table = grid(values_arranged)

        full_table = table(header, main_table)
        return full_table


    def get_filled_template(self, replace_missing_with):

        import re

        mt = mail_fieldtags

        #null_values_in_template = False

        # Don't need separate logic for the two templates:
        # the DNS tag isn't in the non-BigVendor dealer template,
        # so we can run the template.replace() for that pair
        # and nothing will happen.

        replacing = {mt['greeting_name']: self.greeting_name,
                     mt['fso']: self.order_id,
                     mt['date']: self.expected_date,
                     mt['tracknum']: self.tracking_number,
                     mt['a_name']: self.name_line,
                     mt['a_address']: self.address_html,
                     mt['a_citysz']: self.citysz_line,
                     mt['itemtable']: self.get_html_item_table(),
                     }

        try:
            assert all([s is not None for s in replacing.values()]) #not including dns
        except AssertionError:
            raise

        if self.is_BigVendor:
            template = BigVendor_email_template
            assert self.dns is not None
            replacing[mt['dns']] = self.dns  # add to list of replacement fields
            #For BigVendor orders, greet recipient with the "Name" field taken from packing slips 
            #(this is also used in address lines for both BigVendor and non-BigVendor orders)
            #replacing[mt['dealer_name']] = self.name_line

        else:
            #For non-BigVendor orders, greet recipient with the name from contacts CSV
            #replacing[mt['dealer_name']] = self.contact_name
            template = dlr_email_template
            assert self.dns is None

        # The template has some local path stuff mixed in, so we need to expand
        # the text to replace to be the entire URL around 'placetrackingstringhere'

        link_tag = re.findall(r"<A HREF=.*" + "placetrackingstringhere" + "\">",
                              template)[0]
        replacing[link_tag] = '<A HREF="%s">' % (params['ups_web_root']
                                                 + self.tracking_number)

        try:
            # MS word adds a lot of stuff in the header that isn't useful
            # for stying these emails. It's very long, and I would worry that
            # some mail servers might complain about it. (e.g., Gmail sometimes gives a 
            # "long message, click if you want to open this anyway" warning to recipients.)
            template = template.split("</HEAD>")[1]
            # Removing the end-of-file tag-- just in case we might want to stack
            # a bunch of emails into a single HTML file, e.g., as a preview before sending
            template = template.replace("</HTML>", "")
        except:
            pass

        for field, value in replacing.items():  # the keys are each of the replaced codes
            try:
                assert field in template
            except AssertionError:
                log("field not found in template: %s" % field)
            if value is None:
                value = replace_missing_with
            template = template.replace(field, str(value))

        return template



def dtable_query(dtable, index_field, index_id, output_field):
    for row in dtable:
        if row[index_field] == index_id:
            return row[output_field]
    else:
        raise TableRecordNotFound(index_field, index_id)


def get_expected_date(tracking_number):
    '''check expected format, e.g., 1Z6351950343296108
     then pull up information from UPS-querying module'''

    #from upsdata import tracking_info
    #import upsdata

    tracking_number = str(tracking_number)
    # if completely numeric, it was converted to int earlier

    if not tracking_number:
        raise upsdata.TrackingNumberInvalid
    elif len(tracking_number) == 12 and tracking_number.isdigit():
        raise upsdata.TrackingNumberInvalid  # Fedex    
    elif len(tracking_number) != 18 or tracking_number[0:2].upper() != "1Z":
        raise upsdata.TrackingNumberInvalid  # Non-UPS-formatted, unknown
    try:
        track_result = upsdata.tracking_info(userid=params['ups_userid'],
                                             password=params['ups_password'],
                                             access_license=params['ups_access_license'],
                                             tracking_number=tracking_number)
        return track_result
    except:
        raise


def send_internal_email(subject, content):
    log("Sending internal email, subject: %s" % subject)
    if params['email_in_testing_mode']:
        recipient = params['test_email_recipient_as_contactupdating']
    else:
        recipient = params['email_address_for_contact_info_updating']
    #if not params['gmail_password']:
    #    params['gmail_password'] = getpass("Gmail password: ")

    result = send_gmail(gmail_username=params['gmail_userid'],
                        gmail_pwd=params['gmail_password'],
                        send_from=params['email_from_name_for_internal_notes'],
                        send_to=recipient,
                        cc_to=None,
                        subject=subject,
                        html_content=content,
                        simulation_mode=params['simulated_emails'],
                        )
    log(result)

def get_address_fields(slip_id, string_if_empty):

    def query_slips(output_field):
        qs = partial(dtable_query, dtable=pslips_dtable,
                          index_field=pslips_heading['slip_id'],
                          index_id=slip_id)
        try:
            out = qs(output_field)
            if not out: 
                out = string_if_empty
        except TableRecordNotFound as e:
            raise e("slip ID not found")


    #format address lines for one HTML replacement field

    name_line = query_slips(output_field=pslips_heading['addr_name'])

    address_fields = [pslips_heading['addr_line1'],
                      pslips_heading['addr_line2'],
                      pslips_heading['addr_line3']]

    address_lines = [query_slips(output_field=f) for f in address_fields]

    address_lines_nonblank = filter(len, address_lines)
    address_html = '<br>'.join(address_lines_nonblank)

    #format final address line

    city = query_slips(output_field=pslips_heading['addr_city'])
    state = query_slips(output_field=pslips_heading['addr_state'])
    pcode = query_slips(output_field=pslips_heading['addr_pcode'])
    citysz_line = '{c}, {s} {p}'.format(c=city, s=state, p=pcode)

    return name_line, address_html, citysz_line


def get_contact_email(customer_id):
    # Contact table information (often missing)

    query_contact = partial(dtable_query, dtable=contacts_dtable,
                            index_field=contacts_heading['cust_id'],
                            index_id=customer_id)

    try:
        #contact_name = query_contact(output_field=contacts_heading['name'])
        contact_email = query_contact(output_field=contacts_heading['email'])
    except TableRecordNotFound as e:
        raise ContactInfoMissing(customer_id)

    if contact_email:
        try:
            assert len(contact_email) > 0
            assert "@" in contact_email and "." in contact_email
        except AssertionError as e:
            log('Email address record found for cust.id [%s] but name is blank or'
                ' does not match an email address format.'
                % customer_id)
            raise ContactInfoMissing(e.args)

    #if contact_email:
    #    try:
    #        assert len(contact_email) > 0 and '@' in contact_email
    #        # could also use a proper regex for email validation
    #    except AssertionError as e:
    #        log('Contact record found for cust.id [%s] but email is blank or invalid'
    #            % customer_id)
    #        raise ContactInfoMissing(e.args)

    return contact_email


def run_job():

    # Convert all convertable strings to a numeric type
    for table in [contacts_dtable, shipments_dtable, pslips_dtable]:
        for row in table:
            for key in row.keys():
                if row[key].isdigit():
                    row[key] = int(row[key])

    all_slip_ids = [r[pslips_heading['slip_id']]
                    for r in pslips_dtable]
    unique_slip_ids = sorted(set(all_slip_ids))

    notifications = []

    for slip_id in unique_slip_ids:
        log('=' * 80)
        log("Starting slip [%s]" % slip_id)

        n = Notification(slip_id)
        notifications.append(n)


def log(line):
    timestamp = time.strftime("%H:%M:%S")
    datestamp = time.strftime("%Y/%m/%d")
    print "%s %s: %s" % (datestamp, timestamp, line)
    logging.info(line)


def send_gmail(gmail_username, gmail_pwd,
               send_from, send_to, cc_to,
               subject, html_content, simulation_mode):
    ''' send_from is the name associated with the account--
        it will show as being sent from the gmail account's 
        address as well. '''

    if simulation_mode:
        log("Using simulation mode.")
        # save file
        output_filename = "test_email_for_" + send_to

        while os.path.exists(output_filename + '.html'):
            output_filename += " next"

        output_filename += '.html'

        row = lambda text: "<P><B>%s</B></P>\n" % text
        output = (row('TO: ' + repr(send_to)) +
                  row('CC: ' + repr(cc_to)) +
                  row('SUBJECT: ' + repr(subject)) +
                  html_content)

        with open(output_filename, "w") as out_file:
            out_file.write(output)
        result = "Simulated email saved as %s" % output_filename

    else:
        #set email metadata
        msg = MIMEMultipart()
        msg['From'] = send_from
        msg['To'] = send_to
        msg['CC'] = cc_to  
        msg['Date'] = formatdate(localtime=True)
        msg['Subject'] = subject

        #attach email content, tagged as an HTML-based email
        msg.attach(MIMEText(html_content, 'html'))

        #log in to gmail outgoing server and submit
        server = smtplib.SMTP("smtp.gmail.com", 587)
        try:
            server.ehlo()
            server.starttls()
            server.ehlo
            login_result = server.login(gmail_username, gmail_pwd)
            log("Email server login result:" + str(login_result))
            server.sendmail(send_from, send_to, msg.as_string())
            result = "Done: no errors reported by mail server."
        except smtplib.SMTPException as e:
            result = "Error reported by email server: %s" % str(e)
        finally:
            server.quit()
    return result


def test(slip_id="9990007"):
    test1 = Notification(slip_id=slip_id)
    try:
        print test1.email_content
        with open("test_email_slip_%s.html" % str(slip_id), "w") as text_file:
            text_file.write(test1.email_content)
    except AttributeError:
        log("no email generated.")
    log(str(dir(test1)))


def main():
    parser = argparse.ArgumentParser(description='UPS lookup & email '
                                     'template filling and sending.')
    parser.add_argument('--password', dest='gmail_pass', type=str,
                        help="gmail password (username is hard-coded in parameters)",
                        required=False)

    args = parser.parse_args()
    
    if args.gmail_pass:
        params['gmail_password'] = args.gmail_pass
    elif 'gmail_password' not in params:
        raise UserWarning('gmail password not in config or command line arguments')

    #params['gmail_password'] = args.gmail_pass

    run_job()


if __name__ == '__main__':
    main()