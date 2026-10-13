import json
import urllib.request
import xml.etree.ElementTree as ET

BASE = "https://api.ibb.gov.tr/iett/"
ENVELOPE = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body>'
    '<{m} xmlns="http://tempuri.org/">{p}</{m}>'
    "</soap:Body></soap:Envelope>"
)


def _tag(element):
    return element.tag.rsplit("}", 1)[-1]  # drop the XML namespace


def call(service, method, params=""):
    """Call an IETT SOAP method. `_json` methods return parsed JSON, `_GYY` methods a list of dicts."""
    request = urllib.request.Request(
        BASE + service,
        data=ENVELOPE.format(m=method, p=params).encode("utf-8"),
        headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": f'"http://tempuri.org/{method}"'},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        root = ET.fromstring(response.read())
    result = next(e for e in root.iter() if _tag(e) == method + "Result")
    if method.endswith("_json"):
        return json.loads(result.text)
    if len(result) == 0 and result.text:  # result may arrive as escaped XML text
        result = ET.fromstring(result.text)
    return [{_tag(f): f.text for f in row} for row in result.iter() if _tag(row) == "Table"]


def fetch_stops():
    """All stop lists: (line, direction) -> [(code, name, lat, lon)] in route order."""
    rows = call("ibb/ibb.asmx", "DurakDetay_GYY", "<hat_kodu></hat_kodu>")
    rows.sort(key=lambda r: int(r["SIRANO"]))
    stops = {}
    for r in rows:
        stops.setdefault((r["HATKODU"], r["YON"]), []).append(
            (r["DURAKKODU"], r["DURAKADI"], float(r["YKOORDINATI"]), float(r["XKOORDINATI"])))
    return stops
