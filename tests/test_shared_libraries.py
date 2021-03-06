import unittest
from unittest.mock import Mock
from unittest.mock import MagicMock
from unittest.mock import patch
import sys
import boto3
import requests
import json
from moto import mock_ec2, mock_iam, mock_dynamodb2, mock_sts, mock_ssm
sys.path.append('../src/shared_libraries')
import aws_services
import kp_processing
import instance_processing
import pvwa_api_calls as pvwa_api
from pvwa_integration import PvwaIntegration

MOTO_ACCOUNT = '123456789012'
UNIX_PLATFORM = "UnixSSHKeys"
WINDOWS_PLATFORM = "WinServerLocal"
INSTANCE_ID = 'i-8eff23cd'

@mock_iam
@mock_dynamodb2
@mock_sts
@mock_ec2
@mock_ssm
class AwsServicesTest(unittest.TestCase):
    ssm = boto3.client('ssm')
    ssm.put_parameter(
        Name='AOB_Debug_Level',
        Description='string',
        Value='Trace',
        Type='String',
        Overwrite=True)

    def test_get_account_details(self):
        print('test_get_account_details')
        solution_account_id = boto3.client('sts').get_caller_identity().get('Account')
        event_region = 'eu-west-2'
        diff_accounts = aws_services.get_account_details('138339392836', solution_account_id, event_region)
        same_account = aws_services.get_account_details(solution_account_id, solution_account_id, event_region)
        self.assertEqual('ec2.ServiceResource()', str(diff_accounts))
        self.assertEqual('ec2.ServiceResource()', str(same_account))

    def test_get_ec2_details(self):
        print('test_get_ec2_details')
        ec2_resource = boto3.resource('ec2')
        ec2_linux_object, ec2_windows_object = generate_ec2(ec2_resource)
        linux = aws_services.get_ec2_details(ec2_linux_object, ec2_resource, '138339392836')
        windows = aws_services.get_ec2_details(ec2_windows_object, ec2_resource, '138339392836')
        self.assertIn('Amazon Linux', linux['image_description'])
        self.assertIn('Windows', windows['image_description'])

    def test_get_instance_data_from_dynamo_table(self):
        print('test_get_instance_data_from_dynamo_table')
        ec2_resource = boto3.resource('ec2')
        ec2_linux_object, ec2_windows_object = generate_ec2(ec2_resource)
        dynamodb = boto3.resource('dynamodb')
        table = dynamo_create_instances_table(dynamodb)
        dynamo_put_ec2_object(dynamodb, ec2_linux_object)
        new_response = aws_services.get_instance_data_from_dynamo_table(ec2_windows_object)
        exist_response = aws_services.get_instance_data_from_dynamo_table(ec2_linux_object)
        self.assertFalse(new_response)
        self.assertEqual(str(exist_response), f'{{\'InstanceId\': {{\'S\': \'{ec2_linux_object}\'}}}}')
        table.delete()

    def test_put_instance_to_dynamo_table(self):
        print('test_put_instance_to_dynamo_table')
        ec2_resource = boto3.resource('ec2')
        ec2_linux_object, ec2_windows_object = generate_ec2(ec2_resource)
        dynamodb = boto3.resource('dynamodb')
        table = dynamo_create_instances_table(dynamodb)
        on_boarded = aws_services.put_instance_to_dynamo_table(ec2_linux_object, '1.1.1.1', 'on boarded')
        on_boarded_failed = aws_services.put_instance_to_dynamo_table(ec2_linux_object, '1.1.1.1', 'on board failed')
        delete_failed = aws_services.put_instance_to_dynamo_table(ec2_linux_object, '1.1.1.1', 'delete failed')
        self.assertTrue(on_boarded)
        self.assertTrue(on_boarded_failed)
        self.assertTrue(delete_failed)
        table.delete()

    def test_release_session_on_dynamo(self):
        print('test_release_session_on_dynamo')
        sessions_table_lock_client = Mock()
        self.assertTrue(aws_services.release_session_on_dynamo('123', '222332', sessions_table_lock_client))
        sessions_table_lock_client = MagicMock(Exception('AssertError'))
        self.assertFalse(aws_services.release_session_on_dynamo('123', '222332', sessions_table_lock_client))

    def test_remove_instance_from_dynamo_table(self):
        print('test_remove_instance_from_dynamo_table')
        ec2_resource = boto3.resource('ec2')
        ec2_linux_object, ec2_windows_object = generate_ec2(ec2_resource)
        dynamodb = boto3.resource('dynamodb')
        table = dynamo_create_instances_table(dynamodb)
        aws_services.put_instance_to_dynamo_table(ec2_linux_object, '1.1.1.1', 'on boarded')
        remove_linux = aws_services.remove_instance_from_dynamo_table(ec2_linux_object)
        remove_windows = aws_services.remove_instance_from_dynamo_table(ec2_windows_object)
        self.assertTrue(remove_linux)
        self.assertTrue(remove_windows)
        table.delete()

    def test_get_session_from_dynamo(self):
        print('test_get_session_from_dynamo')
        sessions_table_lock_client = Mock()
        def fake_acquire(a, b):
            return 'ab-1232'
        @patch.object(sessions_table_lock_client, 'acquire', fake_acquire)
        def invoke():
            session_number, guid = aws_services.get_session_from_dynamo(sessions_table_lock_client)
            return session_number, guid
        session_number, guid = invoke()
        self.assertIn('mock.guid', str(guid))
        self.assertEqual(type('1'), type(session_number))
        @patch.object(sessions_table_lock_client, 'acquire', fake_exc)
        def invoke2():
            with self.assertRaises(Exception) as context:
                aws_services.get_session_from_dynamo(sessions_table_lock_client)
            self.assertTrue('fake_exc' in str(context.exception))
        invoke2()

    def test_update_instances_table_status(self):
        print('test_update_instances_table_status')
        ec2_resource = boto3.resource('ec2')
        ec2_linux_object, ec2_windows_object = generate_ec2(ec2_resource)
        dynamodb = boto3.resource('dynamodb')
        table = dynamo_create_instances_table(dynamodb)
        status = aws_services.update_instances_table_status(ec2_linux_object, 'on boarded')
        self.assertTrue(status)
        table.delete()

@mock_iam
@mock_dynamodb2
@mock_sts
@mock_ec2
@mock_ssm
class KpProcessingTest(unittest.TestCase):
    def test_save_key_pair(self):
        print('test_save_key_pair')
        with open('pemValue.pem', 'r') as file:
            keyf = file.read()
        kp = kp_processing.save_key_pair(keyf)
        self.assertEqual(None, kp)

    def test_convert_pem_to_ppk(self):
        print('test_convert_pem_to_ppk')
        with open('pemValueM.pem', 'r') as file:
            keyf = file.read()
        ppk_key = kp_processing.convert_pem_to_ppk(keyf)
        self.assertIn('Private-MAC:', ppk_key)
        with self.assertRaises(Exception) as context:
            kp_processing.convert_pem_to_ppk('3')
        self.assertEqual(Exception, type(context.exception))

    def test_decrypt_password(self):
        print('test_decrypt_password')
        command = kp_processing.decrypt_password(
            'V2KFpNbdQM5x90z7KCSqU2Iw8t/kA+8WhWpngtbrZ737Jax9Hj6RBPqyB+qrT0kpVAiAJ9+oXHIU8d7y2OlGdYWjPGB/FFJ'\
            'aVDcOsX+kwQBzeVswv+aD2GgnhvoSRX3feanN7jjbBOLpE+BpqV6a97qYiDSEoEU6l22Vh1TVlMUQ+rytt7c8oUnT3s/nJc01xFSmE1tVx6QNCeJLY'\
            'yfAJCkj6dWYJj7SxpReuBuqmyqvGiPe3pEFDqpl+Tvkz2qg62f8WYWv2dYdQ+/NLFL6nwEKQnyQjBfYoZfmrJev9kejHqLf3zjNWxYK+L62F8g1gZS'\
            'TNkB3U4IDrg/vLiB4YQ==')
        self.assertEqual('Ziw$B-HC-9cLEZ?ypza$PUdWQdliW-i9', command[1])

@mock_iam
@mock_dynamodb2
@mock_sts
@mock_ec2
@mock_ssm
class InstanceProcessingTest(unittest.TestCase):
    pvwa_integration_class = PvwaIntegration()
    def test_delete_instance(self):
        print('test_delete_instance')
        ec2_class = EC2Details()
        ec2_resource = boto3.resource('ec2')
        linux, windows = generate_ec2(ec2_resource)
        req = Mock()
        req.status_code = 200
        dynamodb = boto3.resource('dynamodb')
        table = dynamo_create_instances_table(dynamodb)
        dynamo_put_ec2_object(dynamodb, linux)
        @patch('requests.get', return_value='', status_code='')
        @patch('pvwa_integration.PvwaIntegration.call_rest_api_delete', return_value=req)
        def invoke(*args):
            with patch('pvwa_api_calls.retrieve_account_id_from_account_name') as mp:
                mp.return_value = '1231'
                deleted_instance = instance_processing.delete_instance(windows, 1,ec2_class.sp_class, ec2_class.instance_data,
                                                                       ec2_class.details)
                failed_instance = instance_processing.delete_instance(linux, 2, ec2_class.sp_class, ec2_class.instance_data, ec2_class.details)     
            return deleted_instance, failed_instance
        return_windows, return_linux = invoke('a', 'b')
        self.assertTrue(return_windows)
        self.assertTrue(return_linux)
        table.delete()

    def test_get_instance_password_data(self):
        print('test_get_instance_password_data')
        ec2_resource = boto3.resource('ec2')
        linux, windows = generate_ec2(ec2_resource)
        with patch('boto.ec2.connection.EC2Connection.get_password_data', return_value='StrongPassword'): #### to improve
            respone = instance_processing.get_instance_password_data(windows, MOTO_ACCOUNT, 'eu-west-2', MOTO_ACCOUNT)
        self.assertEqual(None, respone)

    def test_create_instance_windows(self): #### split this module!!!!
        print('test_create_instance_windows')
        ec2_resource = boto3.resource('ec2')
        linux, windows = generate_ec2(ec2_resource)
        ec2_class = EC2Details()
        response = func_create_instance(ec2_class, windows)
        self.assertTrue(response)

    def test_create_instance_linux(self):
        print('test_create_instance_linux')
        ec2_resource = boto3.resource('ec2')
        linux, windows = generate_ec2(ec2_resource)
        ec2_class = EC2Details()
        ec2_class.set_platform('linix')
        ec2_class.set_image_description('Linix')
        response = func_create_instance(ec2_class, windows)
        self.assertTrue(response)

    def test_get_os_distribution_user(self):
        user = instance_processing.get_os_distribution_user('centos')
        self.assertEqual(user, 'centos')
        user = instance_processing.get_os_distribution_user('ubuntu')
        self.assertEqual(user, 'ubuntu')
        user = instance_processing.get_os_distribution_user('debian')
        self.assertEqual(user, 'admin')
        user = instance_processing.get_os_distribution_user('opensuse')
        self.assertEqual(user, 'root')
        user = instance_processing.get_os_distribution_user('fedora')
        self.assertEqual(user, 'fedora')
        user = instance_processing.get_os_distribution_user('Lemon')
        self.assertEqual(user, 'ec2-user')

class PvwaApiCallsTest(unittest.TestCase):
    def test_create_account_on_vault(self):
        ec2_class = EC2Details()
        method = 'create_account_on_vault'
        parameters = ['1', 'my_account','password', ec2_class.sp_class, UNIX_PLATFORM, '1.1.1.1',
                      INSTANCE_ID, 'user', 'safe']
        response = mock_pvwa_integration(method, parameters, 201)
        self.assertTrue(response)

    def test_create_account_on_vault_exception(self):
        ec2_class = EC2Details()
        method = 'create_account_on_vault'
        parameters = ['1', 'my_account','password', ec2_class.sp_class, UNIX_PLATFORM, '1.1.1.1',
                      INSTANCE_ID, 'user', 'safe']
        response = mock_pvwa_integration(method, parameters, 404)
        self.assertFalse(response[0])

    def test_rotate_credentials_immediately(self):
        method = 'rotate_credentials_immediately'
        parameters = ['1', 'https://pvwa', MOTO_ACCOUNT, INSTANCE_ID]
        response = mock_pvwa_integration(method, parameters, 200)
        self.assertTrue(response)

    def test_rotate_credentials_immediately_exception(self):
        method = 'rotate_credentials_immediately'
        parameters = ['1', 'https://pvwa', MOTO_ACCOUNT, INSTANCE_ID]
        response = mock_pvwa_integration(method, parameters, 404)
        self.assertFalse(response)

    def test_get_account_value(self):
        method = 'get_account_value'
        parameters = ['1', MOTO_ACCOUNT, INSTANCE_ID, 'https://pvwa']
        response = mock_pvwa_integration(method, parameters, 200)
        self.assertEqual('', response)

    def test_get_account_value_not_found(self):
        method = 'get_account_value'
        parameters = ['1', MOTO_ACCOUNT, INSTANCE_ID, 'https://pvwa']
        response = mock_pvwa_integration(method, parameters, 404)
        self.assertFalse(response)

    def test_get_account_value_exception(self):
        method = 'get_account_value'
        parameters = ['1', MOTO_ACCOUNT, INSTANCE_ID, 'https://pvwa']
        response = mock_pvwa_integration(method, parameters, 400)
        self.assertFalse(response)

    def test_delete_account_from_vault(self):
        method = "delete_account_from_vault"
        parameters = ['1', MOTO_ACCOUNT, INSTANCE_ID, 'https://pvwa']
        response = mock_pvwa_integration(method, parameters, 200)

    def test_delete_account_from_vault_not_found(self):
        method = "delete_account_from_vault"
        parameters = ['1', MOTO_ACCOUNT, INSTANCE_ID, 'https://pvwa']
        with self.assertRaises(Exception) as context:
            response = mock_pvwa_integration(method, parameters, 404)
        self.assertIn('The account does not exists', str(context.exception))

    def test_delete_account_from_vault_exception(self):
        method = "delete_account_from_vault"
        parameters = ['1', MOTO_ACCOUNT, INSTANCE_ID, 'https://pvwa']
        with self.assertRaises(Exception) as context:
            response = mock_pvwa_integration(method, parameters, 401)
        self.assertIn('Unknown status code received', str(context.exception))

    def test_check_if_kp_exists(self): #### to be fixed
        method = 'check_if_kp_exists'
        parameters = ['1', 'account', 'safe', INSTANCE_ID, 'https://pvwa']
        response = mock_pvwa_integration(method, parameters, 200, True)
        self.assertTrue(response)

    def test_check_if_kp_exists_exception(self):
        method = 'check_if_kp_exists'
        parameters = ['1', 'account', 'safe', INSTANCE_ID, 'https://pvwa']
        with self.assertRaises(Exception) as context:
            response = mock_pvwa_integration(method, parameters, 404, False)
        self.assertEqual(Exception, type(context.exception))

    def test_retrieve_account_id_from_account_name(self):
        method = 'retrieve_account_id_from_account_name'
        parameters = ['1', MOTO_ACCOUNT, 'safe', INSTANCE_ID, 'https://pvwa']
        @patch('pvwa_api_calls.filter_get_accounts_result', return_value=True)
        def invoke(*args):
            response = mock_pvwa_integration(method, parameters, 200, True)
            return response
        response = invoke()
        self.assertTrue(response)

    def test_retrieve_account_id_from_account_name_no_match(self):
        method = 'retrieve_account_id_from_account_name'
        parameters = ['1', MOTO_ACCOUNT, 'safe', INSTANCE_ID, 'https://pvwa']
        @patch('pvwa_api_calls.filter_get_accounts_result', return_value=False)
        def invoke(*args):
            response = mock_pvwa_integration(method, parameters, 200, True)
            return response
        response = invoke()
        self.assertFalse(response)

    def test_retrieve_account_id_from_account_name_exception(self):
        method = 'retrieve_account_id_from_account_name'
        parameters = ['1', MOTO_ACCOUNT, 'safe', INSTANCE_ID, 'https://pvwa']
        @patch('pvwa_api_calls.filter_get_accounts_result', return_value=False)
        def invoke(*args):
            with self.assertRaises(Exception) as context:
                response = mock_pvwa_integration(method, parameters, 403, False)
            return context.exception
        response = invoke()
        self.assertEqual(Exception, type(response))

    def test_filter_get_accounts_result(self):
        with open('json_response.json') as json_resp:
            json_str = json.load(json_resp)
        parsed_json_response = json_str['value']
        response = pvwa_api.filter_get_accounts_result(parsed_json_response, '138339392836')
        self.assertEqual('30_4', response)

    def test_filter_get_accounts_result_false(self):
        with open('json_response.json') as json_resp:
            json_str = json.load(json_resp)
        parsed_json_response = json_str['value']
        response = pvwa_api.filter_get_accounts_result(parsed_json_response, INSTANCE_ID)
        self.assertFalse(response)

##General Functions##
def fake_exc(a, b):
    raise Exception('fake_exc')

def generate_ec2(ec2_resource, returnObject=False):
    ec2_linux_object = ec2_resource.create_instances(ImageId='ami-760aaa0f', MinCount=1, MaxCount=5)
    ec2_windows_object = ec2_resource.create_instances(ImageId='ami-56ec3e2f', MinCount=1, MaxCount=5)
    if returnObject:
        return ec2_linux_object, ec2_windows_object
    return ec2_linux_object[0].id, ec2_windows_object[0].id

def dynamo_create_instances_table(dynamo_resource):
    table = dynamo_resource.Table('Instances')
    table = dynamo_resource.create_table(TableName='Instances',
                                         KeySchema=[{"AttributeName": "InstanceId", "KeyType": "HASH"}],
                                         AttributeDefinitions=[{"AttributeName": "InstanceId", "AttributeType": "S"}])
    return table

def dynamo_put_ec2_object(dynamo_resource, ec2_object):
    table = dynamo_resource.Table('Instances')
    table.put_item(Item={'InstanceId': ec2_object})
    return True

def func_create_instance(ec2_class, ec2_object):
    mocky = Mock()
    mocky.return_value = ['1', '2']
    @patch('kp_processing.save_key_pair', return_value=True)
    @patch('instance_processing.get_instance_password_data', return_value='StrongPassword')
    @patch('kp_processing.convert_pem_to_ppk', return_value='VeryValue')
    @patch('kp_processing.decrypt_password', mocky)
    @patch('aws_services.get_session_from_dynamo', return_value=['3', '4'])
    @patch('pvwa_integration.PvwaIntegration.logon_pvwa', return_value='asbhdsyadbasASDUASDUHB2312312')
    @patch('pvwa_api_calls.retrieve_account_id_from_account_name', return_value=False)
    @patch('pvwa_api_calls.create_account_on_vault', return_value=['a','a'])
    @patch('pvwa_api_calls.rotate_credentials_immediately', return_value='a')
    @patch('aws_services.put_instance_to_dynamo_table', return_value='a')
    @patch('pvwa_integration.PvwaIntegration.logoff_pvwa', return_value='a')
    @patch('aws_services.release_session_on_dynamo',return_value='a')
    def invoke(*args):
        status = instance_processing.create_instance(ec2_object, ec2_class.details, ec2_class.sp_class, 'yea', MOTO_ACCOUNT,
                                            'eu-west-2', MOTO_ACCOUNT, '123123132h')
        return status
    response = invoke()
    return response

def mock_pvwa_integration(method, parameters, return_code=int, json_response=None):
    print(parameters)
    dic = {"create_account_on_vault": pvwa_api.create_account_on_vault,
           "retrieve_account_id_from_account_name": pvwa_api.retrieve_account_id_from_account_name,
           "rotate_credentials_immediately": pvwa_api.rotate_credentials_immediately,
           "check_if_kp_exists": pvwa_api.check_if_kp_exists,
           "delete_account_from_vault": pvwa_api.delete_account_from_vault,
           "filter_get_accounts_result": pvwa_api.filter_get_accounts_result,
           "get_account_value": pvwa_api.get_account_value}
    if json_response:
        response, json_response = mock_requests_response(return_code, json_response)
    else:
        response = mock_requests_response(return_code)
    @patch('pvwa_integration.PvwaIntegration.call_rest_api_post', return_value=response)
    @patch('pvwa_integration.PvwaIntegration.call_rest_api_get', return_value=response)
    @patch('pvwa_integration.PvwaIntegration.call_rest_api_delete', return_value=response)
    @patch('requests.Response.json', return_value=json_response)
    def invoke(*args):
        response = dic[method](*parameters)
        print(f'response:  {response}')
        return response
    output = invoke()
    return output

def mock_requests_response(code=int, json_response=None):
    response = requests.Response()
    response.status_code = code
    if json_response:
        with open('json_response.json') as json_resp:
            json_str = json.load(json_resp)
        return response, json_str
    return response

class EC2Details:
    def __init__(self):
        self.details = dict()
        self.details['key_name'] = 'myKey'
        self.details['platform'] = 'windows'
        self.details['image_description'] = 'windows'
        self.details['aws_account_id'] = '199183736223'
        self.details['address'] = '192.192.192.192'
        self.instance_data = {}
        string = {}
        string['S'] = '192.192.192.192'
        self.instance_data["Address"] = string
        self.instance_data['platform'] = 'Linix'
        self.instance_data['image_description'] = 'Very Linix'
        self.sp_class = aws_services.StoreParameters('unix', 'windows', 'user', 'password', '1.1.1.1', 'kp', 'cert',
                                                     'POC', 'trace')
        self.sp_class.pvwa_url = 'https://cyberarkaob.cyberark'

    def set_platform(self, platform):
        self.details['platform'] = platform

    def set_image_description(self, image_description):
        self.details['image_description'] = image_description

if __name__ == '__main__':
    unittest.main()
