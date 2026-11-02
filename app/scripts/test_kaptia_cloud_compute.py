import os
import unittest
from unittest import mock
from scripts.kaptia_cloud_compute import CloudComputeClient, list_providers

class CloudComputeTests(unittest.TestCase):
 def test_requires_https(self):
  with self.assertRaises(ValueError): CloudComputeClient("http://example.test","x"*32)
 def test_requires_long_token(self):
  with self.assertRaises(ValueError): CloudComputeClient("https://example.test","short")
 def test_rejects_unknown_task_type(self):
  with self.assertRaises(ValueError): CloudComputeClient("https://example.test","x"*32).submit("arbitrary_shell","echo unsafe")
 def test_rejects_oversized_source(self):
  with self.assertRaises(ValueError): CloudComputeClient("https://example.test","x"*32).submit("python_script","x"*500001)
 def test_provider_catalog(self):
  providers=list_providers()
  self.assertGreaterEqual(len(providers),8)
  self.assertTrue(all(p["status"]=="supported" for p in providers))
  self.assertTrue(all("endpoint" in p["connection"].lower() or "worker" in p["connection"].lower() for p in providers))
 def test_environment_factory(self):
  with mock.patch.dict(os.environ,{"KAPTIA_CLOUD_ENDPOINT":"https://worker.example","KAPTIA_CLOUD_TOKEN":"t"*32},clear=True):
   client=CloudComputeClient.from_environment()
   self.assertEqual(client.endpoint,"https://worker.example")
   self.assertNotIn("KAPTIA_CLOUD_TOKEN",client.__dict__)

if __name__=="__main__": unittest.main()
