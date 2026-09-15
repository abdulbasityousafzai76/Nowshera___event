import unittest
from unittest.mock import patch
import httpx
from fastapi.testclient import TestClient
from backend.main import app, safe_csv

class APITests(unittest.TestCase):
    def test_validation_and_anonymous_access(self):
        with TestClient(app) as c:
            self.assertEqual(c.get('/api/health').json()['backend'],'python')
            self.assertEqual(c.get('/api/registrations').status_code,401)
            self.assertEqual(c.get('/api/admin/events').status_code,401)
            self.assertEqual(c.post('/api/events/not-a-uuid/register').status_code,422)
            self.assertEqual(c.post('/api/admin/events',json={'capacity':-1}).status_code,422)
            for path in ['/events','/admin','/registrations']:
                self.assertEqual(c.get(path).status_code,200)
    def test_backend_rejects_non_admin(self):
        async def mock(request,path,method='POST',data=None,token=None):
            return {'id':'test-user'} if path=='/auth/v1/user' else {'is_admin':False}
        with patch('backend.main.upstream',mock),TestClient(app) as c:
            self.assertEqual(c.get('/api/admin/events',headers={'Authorization':'Bearer test'}).status_code,403)
    def test_token_forwarding(self):
        calls=[]
        async def mock(request,path,method='POST',data=None,token=None):
            calls.append((path,token))
            return {'id':'test-user'} if path=='/auth/v1/user' else []
        with patch('backend.main.upstream',mock),TestClient(app) as c:
            self.assertEqual(c.get('/api/registrations',headers={'Authorization':'Bearer owner-token'}).status_code,200)
        self.assertEqual(calls,[('/auth/v1/user','owner-token'),('/rest/v1/rpc/nec_api','owner-token')])
    def test_csv_formula_injection(self):
        self.assertEqual(safe_csv('=1+1'),"'=1+1")
        self.assertEqual(safe_csv(' @command'),"' @command")
        self.assertEqual(safe_csv('Abdul Basit'),'Abdul Basit')

if __name__=='__main__': unittest.main()
