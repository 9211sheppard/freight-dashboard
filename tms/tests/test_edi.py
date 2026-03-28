import io
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tms import tms as tms_blueprint
from tms import edi as edi_module
import tms.tms_db as tms_db


def _build_isa(sender_id, receiver_id, control_number):
    return "*".join(
        [
            "ISA",
            "00",
            "".ljust(10),
            "00",
            "".ljust(10),
            "ZZ",
            sender_id[:15].ljust(15),
            "ZZ",
            receiver_id[:15].ljust(15),
            "260326",
            "1200",
            "^",
            "00501",
            str(control_number).zfill(9),
            "0",
            "T",
            ">",
        ]
    )


def build_x12(transaction_type, st_control, segments, *, sender="SENDER", receiver="RECEIVER", gs_id="SM", gs_control="1"):
    rows = [
        _build_isa(sender, receiver, gs_control),
        f"GS*{gs_id}*{sender}*{receiver}*20260326*1200*{gs_control}*X*005010",
        f"ST*{transaction_type}*{st_control}*005010",
    ]
    rows.extend(segments)
    rows.append(f"SE*{len(segments) + 2}*{st_control}")
    rows.append(f"GE*1*{gs_control}")
    rows.append(f"IEA*1*{str(gs_control).zfill(9)}")
    return "~".join(rows) + "~"


def build_edifact(message_type, control_number, segments, *, sender="EDSENDER", receiver="EDRECV"):
    rows = [
        f"UNB+UNOA:1+{sender}+{receiver}+260326:1200+{control_number}",
        f"UNH+{control_number}+{message_type}:D:99B:UN",
    ]
    rows.extend(segments)
    rows.append(f"UNT+{len(segments) + 2}+{control_number}")
    rows.append(f"UNZ+1+{control_number}")
    return "'".join(rows) + "'"


class EdiIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_db = tms_db.TMS_DB
        tms_db.TMS_DB = str(Path(self.tempdir.name) / "tms.db")
        tms_db.init_tms_db()

        self.original_inbox = edi_module.EDI_INBOX_DIR
        self.original_archive = edi_module.EDI_ARCHIVE_DIR
        self.original_failed = edi_module.EDI_FAILED_DIR
        edi_module.EDI_INBOX_DIR = Path(self.tempdir.name) / "edi_inbox"
        edi_module.EDI_ARCHIVE_DIR = edi_module.EDI_INBOX_DIR / "archive"
        edi_module.EDI_FAILED_DIR = edi_module.EDI_INBOX_DIR / "failed"
        edi_module.ensure_edi_inbox()

        self.app = Flask(
            __name__,
            template_folder=str(ROOT_DIR / "templates"),
            static_folder=str(ROOT_DIR / "static"),
        )
        self.app.config["TESTING"] = True
        self.app.secret_key = "edi-test-secret"

        @self.app.route("/logout")
        def logout():
            return ""

        self.app.register_blueprint(tms_blueprint)
        self.client = self.app.test_client()

    def tearDown(self):
        edi_module.EDI_INBOX_DIR = self.original_inbox
        edi_module.EDI_ARCHIVE_DIR = self.original_archive
        edi_module.EDI_FAILED_DIR = self.original_failed
        tms_db.TMS_DB = self.original_db
        self.tempdir.cleanup()

    def _db(self):
        conn = sqlite3.connect(tms_db.TMS_DB)
        conn.row_factory = sqlite3.Row
        return conn

    def test_parse_supported_x12_transaction_types(self):
        samples = {
            "204": build_x12("204", "0001", ["B2**ABCD**LOAD-2041", "L11*LOAD-2041*CN", "N1*SH*Lakefront Foods", "N4*Chicago*IL*60601", "N1*CN*Metro Grocers", "N4*Dallas*TX*75001"]),
            "210": build_x12("210", "0002", ["B3*INV-2101*LOAD-2101****20260326*2750*USD", "L11*LOAD-2101*CN"]),
            "211": build_x12("211", "0003", ["BOL*BOL-2111*LOAD-2111", "L11*LOAD-2111*CN", "L5*1*Frozen goods"]),
            "214": build_x12("214", "0004", ["B10*PRO214*LOAD-2141*ABCD", "LX*1", "AT7*D1***20260329*1645*CT", "MS1*Dallas*TX*US"], gs_id="QM"),
            "215": build_x12("215", "0005", ["B4*LOAD-2151*ABCD", "L11*LOAD-2151*CN", "Q7*X6", "DTM*140*20260329", "R4*L*UN*Houston*TX"], gs_id="QM"),
            "850": build_x12("850", "0006", ["BEG*00*NE*PO-8501**20260326", "REF*CN*LOAD-8501", "N1*SF*Lakefront Foods", "N4*Chicago*IL*60601", "N1*ST*Metro Grocers", "N4*Dallas*TX*75001", "PO1*1*10*EA***VN*SKU-1", "PID*F****Frozen goods"], gs_id="PO"),
            "856": build_x12("856", "0007", ["BSN*00*ASN-8561*20260326*1200", "REF*CN*LOAD-8561", "N1*SH*Lakefront Foods", "N1*CN*Metro Grocers", "LIN**CN*CONT-001", "SN1**12400*KG", "PID*F****Frozen goods"], gs_id="SH"),
            "990": build_x12("990", "0008", ["B1*ABCD*LOAD-9901**A"], gs_id="GF"),
            "997": build_x12("997", "0009", ["AK1*SM*5", "AK2*204*0001", "AK5*A", "AK9*A*1*1*1"], gs_id="FA"),
        }

        for transaction_type, raw in samples.items():
            parsed = edi_module.parse_edi_document(raw)[0]
            self.assertEqual(parsed["type"], transaction_type)
            self.assertEqual(parsed["format"], "X12")

        parsed_850 = edi_module.parse_edi_document(samples["850"])[0]
        self.assertEqual(parsed_850["shipment"]["shipment_ref"], "LOAD-8501")
        self.assertEqual(parsed_850["line_items"][0]["description"], "Frozen goods")

        parsed_214 = edi_module.parse_edi_document(samples["214"])[0]
        self.assertEqual(parsed_214["events"][-1]["status"], "Delivered")

        parsed_990 = edi_module.parse_edi_document(samples["990"])[0]
        self.assertTrue(parsed_990["response"]["accepted"])

    def test_parse_supported_edifact_messages(self):
        iftmin = build_edifact(
            "IFTMIN",
            "1",
            [
                "BGM+610+BOOK-1+9",
                "RFF+CN:LOAD-ED-1",
                "DTM+133:20260327:102",
                "DTM+132:20260329:102",
                "NAD+CZ+++Lakefront Foods+123 Origin St+Chicago+IL+60601+US",
                "NAD+CN+++Metro Grocers+456 Destination Ave+Dallas+TX+75001+US",
                "GDS+Frozen goods",
            ],
        )
        iftsta = build_edifact(
            "IFTSTA",
            "2",
            [
                "RFF+CN:LOAD-ED-2",
                "STS+1+DEL",
                "DTM+137:20260329:102",
                "LOC+11+Dallas, TX",
            ],
        )
        invoic = build_edifact(
            "INVOIC",
            "3",
            [
                "BGM+380+INV-ED-1+9",
                "RFF+CN:LOAD-ED-3",
                "MOA+9:1995",
                "CUX+2:USD",
                "DTM+137:20260330:102",
            ],
        )

        parsed_iftmin = edi_module.parse_edi_document(iftmin)[0]
        parsed_iftsta = edi_module.parse_edi_document(iftsta)[0]
        parsed_invoic = edi_module.parse_edi_document(invoic)[0]

        self.assertEqual(parsed_iftmin["shipment"]["shipment_ref"], "LOAD-ED-1")
        self.assertEqual(parsed_iftsta["events"][-1]["status"], "Delivered")
        self.assertEqual(parsed_invoic["invoice"]["amount"], 1995.0)

    def test_generate_supported_outbound_documents_round_trip(self):
        shipment = {
            "shipment_ref": "LOAD-GEN-1",
            "carrier_scac": "ABCD",
            "carrier_name": "Acme Carrier",
            "shipper_name": "Lakefront Foods",
            "shipper_address": "123 Origin St",
            "origin_port": "Chicago, IL",
            "consignee_name": "Metro Grocers",
            "consignee_address": "456 Destination Ave",
            "destination_port": "Dallas, TX",
            "status": "In Transit",
            "etd": "2026-03-27",
            "eta": "2026-03-29",
            "cargo_description": "Frozen goods",
            "containers": "CONT-001",
            "weight_kg": 12400,
        }

        outbound_204 = edi_module.generate_204(shipment, "TMSCLIENT", "ABCD")
        outbound_214 = edi_module.generate_214(shipment, "TMSCLIENT", "ABCD", event={"status": "Delivered", "location": "Dallas, TX"})
        outbound_215 = edi_module.generate_215(shipment, "TMSCLIENT", "ABCD", event={"status": "In Transit", "location": "Houston, TX"})
        outbound_856 = edi_module.generate_856(shipment, "TMSCLIENT", "ABCD")
        outbound_990 = edi_module.generate_990(shipment, "TMSCLIENT", "ABCD", response_code="A")
        outbound_997 = edi_module.generate_997(edi_module.parse_edi_document(outbound_204)[0])
        outbound_iftsta = edi_module.generate_iftsta(shipment, "TMSCLIENT", "EDPARTNER", event={"status": "Delivered", "location": "Dallas, TX"})

        self.assertEqual(edi_module.parse_edi_document(outbound_204)[0]["type"], "204")
        self.assertEqual(edi_module.parse_edi_document(outbound_214)[0]["events"][-1]["status"], "Delivered")
        self.assertEqual(edi_module.parse_edi_document(outbound_215)[0]["type"], "215")
        self.assertEqual(edi_module.parse_edi_document(outbound_856)[0]["shipment"]["shipment_ref"], "LOAD-GEN-1")
        self.assertTrue(edi_module.parse_edi_document(outbound_990)[0]["response"]["accepted"])
        self.assertEqual(edi_module.parse_edi_document(outbound_997)[0]["type"], "997")
        self.assertEqual(edi_module.parse_edi_document(outbound_iftsta)[0]["type"], "IFTSTA")

    def test_upload_auto_detects_x12_and_edifact_and_generates_acks(self):
        tms_db.save_edi_partner("X12 Partner", "SENDER", "X12", "inbound")
        tms_db.save_edi_partner("EDI Partner", "EDSENDER", "EDIFACT", "inbound")

        x12_payload = build_x12("204", "0010", ["B2**ABCD**LOAD-UP-1", "L11*LOAD-UP-1*CN", "N1*SH*Lakefront Foods", "N4*Chicago*IL*60601", "N1*CN*Metro Grocers", "N4*Dallas*TX*75001"])
        edifact_payload = build_edifact(
            "IFTMIN",
            "11",
            [
                "BGM+610+BOOK-11+9",
                "RFF+CN:LOAD-UP-2",
                "NAD+CZ+++Lakefront Foods+123 Origin St+Chicago+IL+60601+US",
                "NAD+CN+++Metro Grocers+456 Destination Ave+Dallas+TX+75001+US",
                "GDS+Frozen goods",
            ],
        )

        for filename, payload in [("load204.edi", x12_payload), ("booking.edi", edifact_payload)]:
            response = self.client.post(
                "/tms/edi/upload",
                data={"edi_file": (io.BytesIO(payload.encode("utf-8")), filename)},
                content_type="multipart/form-data",
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 302)

        with closing(self._db()) as conn:
            refs = {row["shipment_ref"] for row in conn.execute("SELECT shipment_ref FROM shipments").fetchall()}
            self.assertIn("LOAD-UP-1", refs)
            self.assertIn("LOAD-UP-2", refs)

            transactions = conn.execute(
                "SELECT direction, type, format, status FROM edi_transactions ORDER BY id"
            ).fetchall()
            self.assertEqual(
                [(row["direction"], row["type"], row["format"]) for row in transactions],
                [
                    ("inbound", "204", "X12"),
                    ("outbound", "997", "X12"),
                    ("inbound", "IFTMIN", "EDIFACT"),
                    ("outbound", "997", "X12"),
                ],
            )

    def test_status_update_generates_outbound_214(self):
        tms_db.save_edi_partner("X12 Partner", "SENDER", "X12", "inbound")
        inbound_204 = build_x12("204", "0011", ["B2**ABCD**LOAD-STAT-1", "L11*LOAD-STAT-1*CN"], sender="SENDER")
        self.client.post(
            "/tms/edi/upload",
            data={"edi_file": (io.BytesIO(inbound_204.encode("ascii")), "status204.edi")},
            content_type="multipart/form-data",
            follow_redirects=False,
        )

        response = self.client.post("/tms/shipments/LOAD-STAT-1/status", json={"status": "Delivered"})
        self.assertEqual(response.status_code, 200)

        with closing(self._db()) as conn:
            row = conn.execute(
                "SELECT direction, type, shipment_ref FROM edi_transactions WHERE direction='outbound' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            self.assertEqual((row["direction"], row["type"], row["shipment_ref"]), ("outbound", "214", "LOAD-STAT-1"))

    def test_partner_management_and_inbox_scan(self):
        response = self.client.post(
            "/tms/edi/partners",
            data={"name": "Inbox Partner", "isa_id": "BOXPARTNER", "format": "X12", "direction": "inbound"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        inbox_file = edi_module.EDI_INBOX_DIR / "inbox-204.edi"
        inbox_file.write_text(build_x12("204", "0012", ["B2**ABCD**LOAD-INBOX-1", "L11*LOAD-INBOX-1*CN"], sender="BOXPARTNER"), encoding="utf-8")
        results = edi_module.scan_edi_inbox_once()
        self.assertEqual(results[0]["status"], "processed")
        self.assertTrue((edi_module.EDI_ARCHIVE_DIR / "inbox-204.edi").exists())

        with closing(self._db()) as conn:
            shipment = conn.execute("SELECT shipment_ref FROM shipments WHERE shipment_ref = 'LOAD-INBOX-1'").fetchone()
            self.assertIsNotNone(shipment)


if __name__ == "__main__":
    unittest.main()
