#!/usr/bin/env python


# Since we have to hard-code the field names, set them
# all up here so they can be changed later if the CSVs change
import csv

# regex used to match and replace a link path in the HTML templates

import logging
import upsdata


class params:
    contacts_csv = 'contacts.csv'
    shipments_csv = 'shipments.csv'
    packingslips_csv = 'packing_slips.csv'
    log_file = 'logfile.txt'
    bigvendor_code = 99999

    dlr_email_template_file = 'Dealer_email.html'
    bigvendor_email_template_file = 'BigVendor_email.html'

    # Credentials created via http://www.ups.com/upsdeveloperkit
    # to avoid hardcoding, run this through the argument parser instead.
    ups_access_license = "XXXXXXXXX"
    ups_userid = "XXXXXXX"
    ups_password = "XXXXXXX"

    # Used only for creating the link for an email recipient
    ups_web_root = 'http://wwwapps.ups.com/WebTracking/track?track=yes&trackNums='

    gmail_userid = "xxxxxxx"
    gmail_password = None
    # gmail password is specified with "--password xxxx" command line option.
    # If this flag isn't provided AND the value above isn't set, the user
    # will be prompted for a password for the first email to be sent.

    email_from_name = "Company Name Shipping"
    email_subject_line = "Your order has shipped!"

    email_address_for_company_records = "companyemail+ccrecords_real@gmail.com"
    email_address_for_contact_info_updating = "companyemail+contactupdate_real@gmail.com"

    # The 'simulated_emails' option causes the emailer to create HTML files in the
    # working directory containing the email example, instead of actually sending
    # anything to any email address. Overrides the "testing mode" below.
    simulated_emails = False

    # The 'email_in_testing_mode' option allows email addresses found in the
    # customer contacts sheet to be replaced by these testing addresses.
    # This has no effect if "simulated_emails" is True.
    email_in_testing_mode = False
    test_email_recipient_as_customer = "test+customer_sim@gmail.com"
    test_email_recipient_as_records = "test+ccrecords_sim@gmail.com"
    test_email_recipient_as_contactupdating = "test+contactupdate_sim@gmail.com"

    # date_not_available_message = ... # Implemented in the "upsdata" module


class shipments_heading:
    cust_id = 'Customer'
    bigvendor_ref_id = 'TableFieldBigVendor'


class pslips_heading:
    slip_id = 'Packing Slip'
    cust_id = 'Customer'
    # the input file has two "Customer" columns. 
    # this will match the second (right-hand) one.

    order_id = 'Order'
    bigvendor_ref_id = 'Reference 5'

    addr_name = 'Name'
    addr_line1 = "Address"
    addr_line2 = "Address2"
    addr_line3 = "Address3"
    addr_city = 'City'
    addr_state = 'State/Province'
    addr_pcode = 'Postal Code'

    shipvia = 'Ship Via'
    tracknum = 'Tracking Number'

    description = 'Rev Description'
    partcode = 'Part'
    quantity = 'Qty'


class contacts_heading:
    cust_id = 'Customer'
    name = 'Name'
    email = 'EMail Address'


class mail_fieldtags:
    dealer_name = 'putncdealernamehere'
    bigvendor_tagid = 'putbigvendor_tagidhere'  # Big Vendor Co. orders only
    co_orderid = 'putco_orderidhere'
    date = 'putdatehere'
    tracknum = 'placetrackingnumberhere'
    a_name = 'putnamehere'
    a_address = 'putaddresshere'
    a_citysz = 'putcityszhere'
    itemtable = 'puttablehere'
    # tracklink =  #set below after loading template files


class TemplateValuesIncomplete(Exception):
    pass


class TableRecordNotFound(Exception):
    pass


class ContactRecordNotFound(Exception):
    pass


class ContactInfoIncomplete(Exception):
    pass


global dlr_email_template
global bigvendor_email_template

# change to param reference later (once the params are just the file name)
dlr_email_template = open(params.dlr_email_template_file).read()
bigvendor_email_template = open(params.bigvendor_email_template_file).read()


def log(line):
    print line
    logging.info(line)


global logfile;
logfile = []
#global log_missing_contacts; log_missing_contacts = []

global contacts_dtable
global shipments_dtable
global pslips_dtable
contacts_dtable = list(csv.DictReader(open(params.contacts_csv, 'rU')))
shipments_dtable = list(csv.DictReader(open(params.shipments_csv, 'rU')))
pslips_dtable = list(csv.DictReader(open(params.packingslips_csv, 'rU')))

# Convert all convertable strings to a numeric type
for table in [contacts_dtable, shipments_dtable, pslips_dtable]:
    for row in table:
        for key in row.keys():
            if row[key].isdigit():
                row[key] = int(row[key])


class PackedItem(object):
    def __init__(self, part_code, description, quantity):
        self.part_code = part_code
        self.description = description
        self.quantity = quantity
        # TO ADD: QUANTITY (not included in current data set)

    def __repr__(self):
        template = "PackedItem object: code={0}, descr={1}, quant={2}"
        return template.format(self.part_code, self.description,
                               self.quantity)


class Notification(object):
    def __init__(self, slip_id):

        log('=' * 80)
        log("Started filling fields: Slip [%s]" % slip_id)

        self.slip_id = slip_id

        from functools import partial

        query_slips = partial(dtable_query, dtable=pslips_dtable,
                              index_field=pslips_heading.slip_id,
                              index_id=self.slip_id)

        self.order_id = query_slips(output_field=pslips_heading.order_id)

        tracknum = query_slips(output_field=pslips_heading.tracknum)
        self.tracking_number = str(tracknum).upper().strip()
        self.expected_date = get_expected_date(self.tracking_number)

        self.items = get_item_list(self.slip_id)

        slip_cust_id = query_slips(output_field=pslips_heading.cust_id)

        # for bigvendor customers: compare "Reference 5" to "TableFieldBigVendor" in shipments 
        #   to determine customer ID
        if slip_cust_id == params.bigvendor_code:

            self.is_bigvendor = True
            # get "Reference 5" from packing slip
            self.bigvendor_tagid = query_slips(output_field=pslips_heading.bigvendor_ref_id)

            self.customer_id = dtable_query(dtable=shipments_dtable,
                                            index_field=shipments_heading.bigvendor_ref_id,
                                            index_id=self.bigvendor_tagid,
                                            output_field=shipments_heading.cust_id)
        else:
            self.is_bigvendor = False
            self.bigvendor_tagid = None
            self.customer_id = query_slips(output_field=pslips_heading.cust_id)

        self.name_line, self.address_html, self.citysz_line = get_address_fields(slip_id)

        self.contact_name, self.contact_email = get_contact_information(self.customer_id)

        if self.contact_email:
            try:
                self.email_content = self.get_filled_template()
            except TemplateValuesIncomplete as e:
                log("One or email template values is missing: %s" % repr(e.args))
            log("Finished filling fields: slip [%s]" % slip_id)
        else:
            log("Skipping slip [%s] (no contact email on record)" % slip_id)

    def get_html_item_table(self):

        # table can be rearranged by changing the order of both the
        # heading names and the item attributes here

        heading_names = ['Part No.', 'Description', 'Quantity']

        values_arranged = [(item.part_code,
                            item.description,
                            item.quantity) for item in self.items]

        cell = lambda val: '<td>%s</td>' % val

        row = lambda value_tuple: (  '<tr>'
                                     + ''.join([cell(val) for val in value_tuple])
                                     + '</tr>')

        grid = lambda value_tuple_list: '\n\t'.join([row(i) for i in value_tuple_list])

        header = row(heading_names)
        main_table = grid(values_arranged)

        # not html5 standard, but still renders in current browsers
        table_tag = '<table cellpadding="3" border="1">'
        table = table_tag + '\n\t%s\n</table>' % '\n\t'.join([header, main_table])
        return table


    def get_filled_template(self):

        # Later updates should replace this clunky test-string-replacement
        # with something more robust (e.g., Jinja?)

        import re

        mt = mail_fieldtags

        # Don't need separate logic for the two templates:
        # the bigvendor_tagid tag isn't in the non-bigvendor dealer template,
        # so we can run the template.replace() for that pair
        # and nothing will happen.

        replacing = {mt.dealer_name: self.contact_name,
                     mt.co_orderid: self.order_id,
                     mt.date: self.expected_date,
                     mt.tracknum: self.tracking_number,
                     mt.a_name: self.name_line,
                     mt.a_address: self.address_html,
                     mt.a_citysz: self.citysz_line,
                     mt.itemtable: self.get_html_item_table()
        }

        if self.is_bigvendor:
            template = bigvendor_email_template
            assert self.bigvendor_tagid is not None
            replacing[mt.bigvendor_tagid] = self.bigvendor_tagid  # add to list of replacement fields

        else:
            template = dlr_email_template
            assert self.bigvendor_tagid is None

        # The template has some local path stuff mixed in, so we need to expand
        # the text to replace to be the entire URL around 'placetrackingstringhere'

        link_tag = re.findall(r"<A HREF=.*" + "placetrackingstringhere" + "\">",
                              template)[0]
        # print link_tag
        replacing[link_tag] = '<A HREF="%s">' % (params.ups_web_root
                                                 + self.tracking_number)

        # print mail_fieldtags

        for field, value in replacing.items():  # the keys are each of the replaced codes

            # Throw an exception if any value is missing, except in the
            # special case of a 
            if value is None:
                raise TemplateValuesIncomplete(field, value)

            str_value = str(value)

            try:
                template = template.replace(field, str_value)
            except TypeError:
                raise

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

        return template


def get_contact_information(customer_id):
    # Contact table information (often missing)

    from functools import partial

    query_contact = partial(dtable_query, dtable=contacts_dtable,
                            index_field=contacts_heading.cust_id,
                            index_id=customer_id)

    try:
        contact_name = query_contact(output_field=contacts_heading.name)
        contact_email = query_contact(output_field=contacts_heading.email)
    except TableRecordNotFound as e:
        raise ContactRecordNotFound(customer_id)

    if contact_name:
        try:
            assert len(contact_name) > 0
        except AssertionError as e:
            log('Contact record found for cust.id [%s] but name is blank'
                % customer_id)
            raise ContactInfoIncomplete(e.args)

    if contact_email:
        try:
            assert len(contact_email) > 0 and '@' in contact_email
            # could also use a proper regex for email validation
        except AssertionError as e:
            log('Contact record found for cust.id [%s] but email is blank or invalid'
                % customer_id)
            raise ContactInfoIncomplete(e.args)

    return contact_name, contact_email


def send_contact_update_email(customer_id):
    from getpass import getpass

    log("Sending an email to update records")

    if params.email_in_testing_mode:
        recipient = params.test_email_recipient_as_contactupdating
    else:
        recipient = params.email_address_for_contact_info_updating

    if not params.gmail_password:
        params.gmail_password = getpass("Gmail password: ")

    subject = ("Notification: missing contact "
               "information for customer ID %s" % customer_id)
    message = subject

    result = send_gmail(gmail_username=params.gmail_userid,
                        gmail_pwd=params.gmail_password,
                        send_from=params.email_from_name,
                        send_to=recipient,
                        cc_to=None,
                        subject=message,
                        html_content=message,
                        simulation_mode=params.simulated_emails,
    )
    log("Contact info update request email sent for customer ID: %s"
        % customer_id)


def send_missing_data_email(slip_id):
    log("Sending an email notification about missing data")

    if params.email_in_testing_mode:
        recipient = params.test_email_recipient_as_records
    else:
        recipient = params.email_address_for_company_records

    subject = "Notification regarding packing slip ID %s" % slip_id
    message = ("Order records are missing data required to "
               "produce a shipment notification email for the "
               "order associated with packing slip ID:  %s" % slip_id)

    result = send_gmail(gmail_username=params.gmail_userid,
                        gmail_pwd=params.gmail_password,
                        send_from=params.email_from_name,
                        send_to=recipient,
                        cc_to=None,
                        subject=subject,
                        html_content=message,
                        simulation_mode=params.simulated_emails,
    )
    log("Contact info update request email sent for Slip ID: %s"
        % slip_id)
    # params.email_address_for_contact_info_updating


def get_address_fields(slip_id):
    #print get_dtable_row(dtable=pslips_dtable,
    #                     index_field=pslips_heading.slip_id,
    #                     index_id=slip_id)

    from functools import partial

    query_slips = partial(dtable_query, dtable=pslips_dtable,
                          index_field=pslips_heading.slip_id,
                          index_id=slip_id)

    #format address lines for one HTML replacement field

    name_line = query_slips(output_field=pslips_heading.addr_name)

    address_fields = [pslips_heading.addr_line1,
                      pslips_heading.addr_line2,
                      pslips_heading.addr_line3]

    address_lines = [query_slips(output_field=f) for f in address_fields]

    address_lines_nonblank = filter(len, address_lines)
    address_html = '<br>'.join(address_lines_nonblank)

    #format final address line

    city = query_slips(output_field=pslips_heading.addr_city)
    state = query_slips(output_field=pslips_heading.addr_state)
    pcode = query_slips(output_field=pslips_heading.addr_pcode)
    citysz_line = '{c}, {s} {p}'.format(c=city, s=state, p=pcode)

    return name_line, address_html, citysz_line


def dtable_query(dtable, index_field, index_id, output_field):
    for row in dtable:
        if row[index_field] == index_id:
            return row[output_field]
    else:
        raise TableRecordNotFound(index_field, index_id)


# used only to print debugging information
def get_dtable_row(dtable, index_field, index_id):
    for row in dtable:
        if row[index_field] == index_id:
            return row
    else:
        raise TableRecordNotFound(index_field, index_id)


def get_item_list(slip_id):
    '''Construct table of items for a given Order ID using the packingslips CSV'''

    import csv


    itemrows = [row for row in pslips_dtable
                if row[pslips_heading.slip_id] == slip_id]

    #the csv includes a "Line" field that counts up for items in an order
    # could be useful as a consistency check while testing...
    countup = [row['Line'] for row in itemrows]
    assert len(countup) == len(set(countup))  # i.e., all unique values
    assert max(countup) - min(countup) == len(countup) - 1

    # not pulling just from the top item per slip id, so we can't use the 
    # query_slips used elsewhere (that just looks on the 
    # top matching row)

    items = [PackedItem(part_code=row[pslips_heading.partcode],
                        description=row[pslips_heading.description],
                        quantity=row[pslips_heading.quantity])
             for row in itemrows]
    if len(items) == 0:
        raise NoSlipIdMatch(slip_id)

    return items


def get_expected_date(tracking_number):
    '''check expected format, e.g., 1Z6351950343296108
     then pull up information from UPS-querying module'''

    #from upsdata import tracking_info
    import upsdata

    tracking_number = str(tracking_number)
    # if completely numeric, it was converted to int earlier

    if not tracking_number:
        raise upsdata.TrackingNumberInvalid

    elif len(tracking_number) == 12 and tracking_number.isdigit():
        raise upsdata.TrackingNumberInvalid  # Fedex    

    elif len(tracking_number) != 18 or tracking_number[0:2].upper() != "1Z":
        raise upsdata.TrackingNumberInvalid  # Non-UPS-formatted, unknown

    try:
        track_result = upsdata.tracking_info(userid=params.ups_userid,
                                             password=params.ups_password,
                                             access_license=params.ups_access_license,
                                             tracking_number=tracking_number)
        return track_result
    except:
        raise


def send_gmail(gmail_username, gmail_pwd,
               send_from, send_to, cc_to,
               subject, html_content, simulation_mode):
    ''' send_from is the name associated with the account--
        it will show as being sent from the gmail account's 
        address as well. '''

    import smtplib
    #from smtplib import SMTPAuthenticationError

    from email.MIMEMultipart import MIMEMultipart
    from email.MIMEText import MIMEText
    from email.Utils import formatdate

    if simulation_mode:
        import os.path

        log("Using simulation mode.")
        # save file
        output_filename = "test_email_for_" + send_to

        while os.path.exists(output_filename + '.html'):
            output_filename += " next"
        output_filename += '.html'

        row = lambda text: "<P><B>%s</B></P>\n" % text
        output = (row('TO: ' + send_to) +
                  row('CC: ' + cc_to) +
                  row('SUBJECT: ' + subject) +
                  html_content)

        with open(output_filename, "w") as out_file:
            out_file.write(output)

        log("Simulated email saved as %s" % output_filename)
        return None

    #set email metadata
    msg = MIMEMultipart()
    msg['From'] = send_from
    msg['To'] = send_to
    msg['CC'] = cc_to  #newly added, untested
    msg['Date'] = formatdate(localtime=True)
    msg['Subject'] = subject

    #attach email content, tagged as an HTML-based email
    msg.attach(MIMEText(html_content, 'html'))

    #log in to gmail outgoing server and submit
    server = smtplib.SMTP("smtp.gmail.com", 587)
    server.ehlo()
    server.starttls()
    server.ehlo

    try:
        server.login(gmail_username, gmail_pwd)
    except smtplib.SMTPAuthenticationError:
        log("INCORRECT LOGIN/PASSWORD")
        return server.quit()

    server.sendmail(send_from, send_to, msg.as_string())

    #log("*** MAIL SENT TO: %s" % send_to)
    return server.quit()


def run_job():
    import csv
    from functools import partial
    from getpass import getpass

    #test_run_rows = range(33, 48)

    unique_slip_ids = sorted(set([r[pslips_heading.slip_id]
                                  for r in pslips_dtable]))

    for slip_id in unique_slip_ids:

        try:
            n = Notification(slip_id)
        except TableRecordNotFound as e:
            error_info = repr(e.args)
            log("CSV input is missing data needed to identify records from slip id: {0}, {1}"
                .format(slip_id, error_info))
            send_missing_data_email(slip_id)  # (n, slip_id?
            continue
        except upsdata.TrackingNumberInvalid as e:
            error_info = repr(e.args)
            log("Tracking number is invalid: {0}, {1}"
                .format(slip_id, error_info))
            send_missing_data_email(slip_id)
            continue
        except TemplateValuesIncomplete as e:
            error_info = repr(e.args)
            log("CSV input is missing data needed to produce email template: %s"
                % error_info)
            send_missing_data_email(slip_id)  # (n, slip_id?
            continue
        except ContactRecordNotFound as e:
            error_info = repr(e.args)
            customerid = e.args[0]
            log("Contact record not found: %s" % error_info)
            send_contact_update_email(customerid)  # ()
            continue
        except ContactInfoIncomplete as e:
            error_info = repr(e.args)
            customerid = e.args[0]
            error_info = repr(e.args)
            log("Contact info incomplete: %s" % error_info)
            send_contact_update_email(customerid)
            continue
        except:
            raise

        if params.email_in_testing_mode:
            cust_address = params.test_email_recipient_as_customer
            cc_address = params.test_email_recipient_as_records
        else:
            cust_address = n.contact_email
            cc_address = params.email_address_for_company_records

        log("Starting email to: %s" % n.contact_email)

        if not params.gmail_password:
            params.gmail_password = getpass("Gmail password: ")

        result = send_gmail(gmail_username=params.gmail_userid,
                            gmail_pwd=params.gmail_password,
                            send_from=params.email_from_name,
                            send_to=cust_address,
                            cc_to=cc_address,
                            subject=params.email_subject_line,
                            html_content=n.email_content,
                            simulation_mode=params.simulated_emails,
        )
        log("Email sent for Slip ID: [%s] to: [%s]" % (n.slip_id, n.contact_email))


def print_info(notification_object):
    n = notification_object

    header = lambda s: '\n' + s.upper() + '\n' + "-" * len(s)

    print '\n' + '=' * 50
    print header("showing info for slip ID: %s" % n.slip_id)
    print header("fields taken directly from packing slip CSV")
    print "associated order id:", n.order_id
    print "tracking number:", n.tracking_number
    print "tracking date message:", get_expected_date(n.tracking_number)
    print "ship-to name:", n.name_line
    print "ship-to street address (multiline html):\n", n.address_html
    print "ship-to citysz_line:", n.citysz_line

    print "\nshipped items:\n", n.items

    print "\nshipped items, as html table:\n", n.get_html_item_table()

    print "\nIs bigvendor dealer? (code %s):" % params.bigvendor_code, n.is_bigvendor

    print header("fields taken from shipments CSV (ref'd by Order ID")
    print ("customer ID (taken directly from slip or referenced from shipments csv if "
           "the ID in the slip is %s" % str(params.bigvendor_code)), ": ", n.customer_id
    print "\nbigvendor_tagid code ('TableFieldBigVendor') if bigvendor dealer:", n.bigvendor_tagid

    print header("fields taken from contacts CSV (ref'd by Customer ID")
    print "contact name:", n.contact_name
    print "contact email:", n.contact_email


def test(slip_id=777777):
    test1 = Notification(slip_id=slip_id)
    #test2 = Notification(slip_id=125775)

    print_info(test1)
    print

    try:
        print test1.email_content
        with open("test_email_slip_%s.html" % str(slip_id), "w") as text_file:
            text_file.write(test1.email_content)
    except AttributeError:
        print ("no email generated.")


def main():
    # Commented code could be brought back if we want to be able to specify
    # CSV files upon executing instead of hard-coding the names in params above.
    import argparse

    parser = argparse.ArgumentParser(description='UPS lookup & email template filling and sending.')
    #parser.add_argument('-c', '--contacts', dest='contacts', type=str, help='CSV containing customer info indexed by "Customer" column')
    #parser.add_argument('-p', '--packingslips', dest='packingslips', type=str, help='CSV containing shipment info indexed by "Ordera xxxxx column')
    #parser.add_argument('-s', '--shipments', dest='shipments', type=str, help="CSV containing a xxxxx column")
    parser.add_argument('--password', dest='gmail_pass', type=str,
                        help="gmail password (username is hard-coded in parameters")
    args = parser.parse_args()

    logging.basicConfig(filename=params.log_file, level=logging.DEBUG)

    #if not all([args.contacts, args.packingslips, args.shipments]):
    #    print args.contacts
    #    print args.packingslips
    #    print args.shipments
    #    raise parser.error("one or more required filenames not included")

    if args.gmail_pass:
        params.gmail_password = args.gmail_pass

    run_job()


if __name__ == '__main__':
    main()



