
from ioc_engine import extract_iocs

ticket = """
Microsoft Defender detected suspicious activity.

Endpoint connected to 192.168.1.50
and attempted communication with suspicious-example.com.

Observed URL:
https://suspicious-example.com/payload.exe

File MD5:
d41d8cd98f00b204e9800998ecf8427e
"""

result = extract_iocs(ticket)

for indicator_type, values in result.items():
    print(f"{indicator_type}: {values}")
