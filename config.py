params = {
    'contacts_csv': 'CUSTOMERCONTACTS.csv',
    'shipments_csv': 'CUSTOMERSHIPMENTS.csv',
    'packingslips_csv': 'PACKINGSLIPS.csv',
    'log_file': 'logfile.txt',
    'BigVendor_code': 2758,

    'dlr_email_template_file': 'Dealer_email.html',
    'BigVendor_email_template_file': 'BigVendor_email.html',

    # Credentials created via http://www.ups.com/upsdeveloperkit
    'ups_access_license': "AAAAAAAAAAAAAAA",
    'ups_userid': "xxxxxx",
    'ups_password': "xxxxxxx",

    # Used only for creating the link for an email recipient
    'ups_web_root': "http://wwwapps.ups.com/WebTracking/track?track=yes&trackNums=",

    'gmail_userid': 'xxxxxxxx',
    'gmail_password': 'xxxxxxxxx',
    # gmail password is specified with "--password xxxx" command line option.

    # This must be set to something that will never appear in a real email,
    # because we're doublechecking before sending them to make sure
    # this text isn't in the email to send.
    'text_placeholder_if_info_missing': '<font color="red">[MISSING]</font>',

    'email_from_name': "[My Company] Shipping",
    'email_subject_line_jd': "Your [Big Vendor] direct order with [My Company] has shipped",
    'email_subject_line_non_jd': "Your order with [My Company] has shipped",

    #(need to build in an additional parameter if there will be different subject lines
    # for JD vs. non-JD orders.)

    'email_from_name_for_internal_notes': "Shipping notification records",

    'email_address_for_company_records': "xxxx@xxxx.com",
    'email_address_for_contact_info_updating': "xxxx@xxxx.com",

    # The 'simulated_emails' option causes the emailer to create HTML files in the
    # working directory containing the email example, instead of actually sending
    # anything to any email address. Overrides the "testing mode" below.
    'simulated_emails': False,

    # The 'email_in_testing_mode' option allows email addresses found in the
    # customer contacts sheet to be replaced by these testing addresses.
    # This has no effect if "simulated_emails" is True.
    'email_in_testing_mode': False,
    'test_email_recipient_as_customer': "xxxx@xxxx.com",
    'test_email_recipient_as_records': "xxxx@xxxx.com",
    'test_email_recipient_as_contactupdating': "xxxx@xxxx.com",
    }

item_column_labels = {
    'part': 'Part No.', 
    'description': 'Description', 
    'quantity': 'Qty'
    }

shipments_heading = {
    'name': 'Name',
    'cust_id': 'Customer',
    'BigVendor_shortchar_lookup': 'ShortChar01',
    }


pslips_heading = {
    'slip_id': 'Packing Slip',
    'cust_id': 'Customer', # program uses only the right-most "Customer" value

    'order_id': 'Order',
    'BigVendor_dns_number': 'Reference 4',
    'BigVendor_shortchar_id': 'Reference 5',
    'addr_name': 'Name',
    'addr_line1': "Address",
    'addr_line2': "Address2",
    'addr_line3': "Address3",
    'addr_city': 'City',
    'addr_state': 'State/Province',
    'addr_pcode': 'Postal Code',

    'shipvia': 'Ship Via',
    'tracknum': 'Tracking Number',

    'description': 'Rev Description',
    'partcode': 'Part',
    'quantity': 'Qty',
    }

contacts_heading = {
    'cust_id': 'Customer',
    'name': 'Name',
    'email': 'EMail Address',
    }

mail_fieldtags = {
    'greeting_name': 'putncdealernamehere',
    'dns': 'putdnshere',  # ["Big Vendor"] orders only
    'fso': 'putfsohere',
    'date': 'putdatehere',
    'tracknum': 'placetrackingnumberhere',
    'a_name': 'putnamehere',
    'a_address': 'putaddresshere',
    'a_citysz': 'putcityszhere',
    'itemtable': 'puttablehere',
    }