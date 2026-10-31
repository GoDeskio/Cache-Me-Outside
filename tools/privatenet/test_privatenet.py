import base64
import ipaddress
import unittest
import privatenet as P

K1 = base64.b64encode(b"\x01" * 32).decode()
K2 = base64.b64encode(b"\x02" * 32).decode()


class T(unittest.TestCase):
    def test_allocation_disjoint(self):
        a, b = P.allocate(0), P.allocate(1)
        self.assertFalse(a.overlaps(b))
        self.assertEqual(P.allocate(8191), ipaddress.ip_network("10.200.255.248/29"))
        with self.assertRaises(ValueError):
            P.allocate(8192)

    def test_gateway(self):
        iface, c = P.gateway_conf(1, 51821, [K1, K2], "10.0.0.5")
        self.assertEqual(iface, "wgt1")
        self.assertIn("Address = 10.200.0.9/29", c)
        self.assertIn("AllowedIPs = 10.200.0.10/32", c)
        self.assertIn("-d 10.0.0.5 -p tcp --dport 6379 -j ACCEPT", c)
        self.assertIn("-j DROP", c)
        self.assertNotIn("PrivateKey", c)
        with self.assertRaises(ValueError):
            P.gateway_conf(0, 1, [K1] * 6, "10.0.0.5")
        with self.assertRaises(ValueError):
            P.gateway_conf(0, 1, ["bad"], "10.0.0.5")

    def test_client(self):
        c = P.client_conf(1, 0, K1, "gw.example:51821", "10.0.0.5")
        self.assertIn("Address = 10.200.0.10/32", c)
        self.assertIn("AllowedIPs = 10.0.0.5/32", c)
        self.assertNotIn("PrivateKey", c)


if __name__ == "__main__":
    unittest.main()
