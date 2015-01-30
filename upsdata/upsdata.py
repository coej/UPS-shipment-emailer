
def TestDirs():
    import os
    import sys
    print "os.getcwd()", os.getcwd()
    print "os.path.abspath('')", os.path.abspath('')
    print "os.path.dirname(__file__)", os.path.dirname(__file__)
    print "sys.path[0]", sys.path[0]
    print "os.path.abspath(os.path.dirname(sys.argv[0]))", os.path.abspath(os.path.dirname(sys.argv[0]))
    __location__ = os.path.realpath(
        os.path.join(os.getcwd(), os.path.dirname(__file__)))
    print "os.path.join(__location__, 'bundled-resource.jpg')", os.path.join(__location__, 'bundled-resource.jpg')
    print "os.path.dirname(__file__)", os.path.dirname(__file__)
    
class TrackingNumberInvalid(Exception):
    pass

def tracking_info(userid, password, access_license, tracking_number, testing=False):
    
    import os
    import urllib2
    from datetime import datetime

    # External open-source XML processing library.
    import xmltodict_static as xmltodict
    # If xmltodict library were installed on the system, could use that instead of 
    # the downloaded xmltodict_static.py file:
    # import xmltodict
    
    no_date_message = ("Delivery date information is not currently available. "
                       "Please see the tracking link for delivery information.")
    ups_testing_url = "https://wwwcie.ups.com/ups.app/xml/Track"
    ups_tracking_url = "https://www.ups.com/ups.app/xml/Track"

    #ups_testing_tracknum = '1Z12345E6692804405' # --> a date in 2010
    
    if testing:
        target_url = ups_testing_url
    else:
        target_url = ups_tracking_url


    # Resource files are in script directory
    __location__ = os.path.realpath(os.path.join(os.getcwd(), os.path.dirname(__file__)))
    xml_template_file = os.path.join(__location__, 'ups_request_template.xml')
    
    #The UPS tracking API requires requests to be structured as XML, so the
    #user information and tracking number are inserted into this XML file template.
    xml_template = open(xml_template_file).read()
    xml_request = xml_template.format(USERID = userid, PASS = password,
                                      ACCESS_LICENSE = access_license,
                                      TRACKING_NUMBER = tracking_number)
                                      
    request = urllib2.Request(target_url, xml_request)
    response = urllib2.urlopen(request)
    xml_result = response.read()
    
    full_result = xmltodict.parse(xml_result)

    root = full_result['TrackResponse']

    # Confirm status code from server is reported as OK
    response_info = root['Response']
    status_code = response_info['ResponseStatusCode']
    if status_code == 0 or 'Error' in response_info:
        try:
            ups_api_error_info = response_info['Error']['ErrorDescription']
            raise TrackingNumberInvalid(ups_api_error_info)
        except:
            raise TrackingNumberInvalid(response_info)
        
    # the UPS API labels the date info differently depending on 
    # whether the scheduled date is unavailable, on schedule, or rescheduled,
    # so we need to check which of these fields has been included.
    shipment = root['Shipment']
    if "DeliveryDateUnavailable" in shipment:
        scheduled_date = None
    if 'Package' in shipment and 'RescheduledDeliveryDate' in shipment['Package']:
    	package = shipment['Package']
        scheduled_date = package['RescheduledDeliveryDate']
    elif 'ScheduledDeliveryDate' in shipment:
        scheduled_date = shipment['ScheduledDeliveryDate']
    else:
        scheduled_date = None
    
    # convert "20141224" format to "12/24/2014" format
    if scheduled_date:
        return datetime.strptime(scheduled_date, '%Y%m%d').strftime('%m/%d/%Y')
    else:
        return no_date_message
    

def Test():
    ups_tester_number = '1Z12345E6692804405'
    #userid = raw_input("userid: ")
    #password = raw_input("password: ")
    #access_license = raw_input("access license number: ")
    
    import sys
    if len(sys.argv) > 1:
        tracking_number = sys.argv[1]
    else:
        tracking_number = ups_tester_number
    
    access_license = "xxxxxx"
    userid = "xxxxxx"
    password = "xxxxxx" 
    
    print TrackingInfo(userid = userid,
                       password = password,
                       access_license = access_license,
                       tracking_number = tracking_number,
                       testing=True)
    
if __name__=='__main__':
    Test()