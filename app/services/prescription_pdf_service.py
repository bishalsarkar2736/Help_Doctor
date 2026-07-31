import logging
from datetime import datetime
from io import BytesIO
from xml.sax.saxutils import escape

from app.security.file_validation import ensure_decodable_image
from app.services.storage import get_storage
from reportlab.lib.colors import Color
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from app.models.clinic import Clinic
from pathlib import Path
from app.core.time import UTC
from app.models.prescription import Prescription,PrescriptionStatus
from reportlab.platypus import Image
from app.utils.qr_service import (
    generate_qr_code,
)

from app.core.prescription_qr import (
    build_prescription_verification_url,
)



logger = logging.getLogger(__name__)

def format_utc(
    dt: datetime | None,
) -> str:

    if not dt:
        return "N/A"

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)

    return dt.astimezone(UTC).strftime(
        "%Y-%m-%d %H:%M UTC"
    )



def draw_superseded_watermark(
    canvas,
    doc,
    prescription: Prescription,
):
    """
    Draw watermark for superseded or locked prescriptions.
    """

    if prescription.status not in [
        PrescriptionStatus.SUPERSEDED,
        PrescriptionStatus.LOCKED,
    ]:
        return

    canvas.saveState()

    canvas.setFont(
        "Helvetica-Bold",
        60,
    )

    canvas.setFillColor(
        Color(
            0.85,
            0.85,
            0.85,
            alpha=0.3,
        )
    )

    canvas.translate(300, 400)

    canvas.rotate(45)

    canvas.drawCentredString(
        0,
        0,
        "SUPERSEDED",
    )

    canvas.restoreState()



def generate_prescription_pdf(
    prescription: Prescription,
    clinic: Clinic | None = None,
) -> bytes:

    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40,
    )

    styles = getSampleStyleSheet()

    elements = []

    # ====================================
    # CLINIC INFO
    # ====================================

    if clinic:

        if clinic.logo_url:

            logo_path = Path(clinic.logo_url)

            if logo_path.exists():

                # Same lazy-Image trap as the signature below: reportlab does
                # not touch the file until doc.build(), so a try/except around
                # the constructor never fires. Check the bytes instead.
                try:
                    ensure_decodable_image(logo_path.read_bytes())

                    elements.append(
                        Image(
                            str(logo_path),
                            width=120,
                            height=60,
                        )
                    )

                    elements.append(
                        Spacer(1, 10)
                    )

                except (ValueError, OSError):
                    logger.warning(
                        "prescription_pdf_logo_unreadable",
                        extra={"logo_path": str(logo_path)},
                    )

        elements.append(
            Paragraph(
                f"<b>{escape(clinic.name)}</b>",
                styles["Title"],
            )
        )

        if clinic.address:
            elements.append(
                Paragraph(
                    escape(clinic.address),
                    styles["Normal"],
                )
            )

        if clinic.phone:
            elements.append(
                Paragraph(
                    f"Phone: {escape(clinic.phone)}",
                    styles["Normal"],
                )
            )

        if clinic.email:
            elements.append(
                Paragraph(
                    f"Email: {escape(clinic.email)}",
                    styles["Normal"],
                )
            )

        if clinic.website:
            elements.append(
                Paragraph(
                    escape(clinic.website),
                    styles["Normal"],
                )
            )

    else:

        elements.append(
            Paragraph(
                "<b>HelpDoctor Clinic</b>",
                styles["Title"],
            )
        )

    elements.append(
        Spacer(1, 20)
    )
        

    # ====================================
    # PRESCRIPTION HEADER
    # ====================================

    elements.append(
        Paragraph(
            (
                f"<b>Prescription ID:</b> "
                f"{prescription.id}"
            ),
            styles["Normal"],
        )
    )

    elements.append(
        Paragraph(
            (
                f"<b>Prescription UUID:</b> "
                f"{prescription.uuid}"
            ),
            styles["Normal"],
        )
    )

    elements.append(
        Paragraph(
            (
                f"<b>Prescription Revision:</b> "
                f"{prescription.revision_number}"
            ),
            styles["Normal"],
        )
    )

    elements.append(
        Paragraph(
            (
                f"<b>Latest Revision:</b> "
                f"{'Yes' if prescription.is_latest_revision else 'No'}"
            ),
            styles["Normal"],
        )
    )

    generated_at = format_utc(
        prescription.created_at
    )

    elements.append(
        Paragraph(
            (
                f"<b>Generated:</b> "
                f"{generated_at}"
            ),
            styles["Normal"],
        )
    )

    elements.append(
        Spacer(1, 15)
    )

    # ====================================
    # DOCTOR INFO
    # ====================================

    doctor_name = (
        prescription.doctor.user.full_name
        if (
            prescription.doctor
            and prescription.doctor.user
            and prescription.doctor.user.full_name
        )
        else f"Doctor #{prescription.doctor_id}"
    )

    elements.append(
        Paragraph(
            (
                f"<b>Doctor:</b> "
                f"{escape(doctor_name)}"
            ),
            styles["Normal"],
        )
    )

    elements.append(
        Spacer(1, 10)
    )

    # ====================================
    # PATIENT INFO
    # ====================================

    patient_name = (
        prescription.patient.full_name
        if (
            prescription.patient
            and prescription.patient.full_name
        )
        else f"Patient #{prescription.patient_id}"
    )

    elements.append(
        Paragraph(
            (
                f"<b>Patient:</b> "
                f"{escape(patient_name)}"
            ),
            styles["Normal"],
        )
    )

    elements.append(
        Paragraph(
            (
                f"<b>Appointment ID:</b> "
                f"{prescription.appointment_id}"
            ),
            styles["Normal"],
        )
    )

    # ====================================
    # APPOINTMENT DATE
    # ====================================

    if (
        prescription.appointment
        and prescription.appointment.scheduled_at
    ):

        scheduled_at = format_utc(
            prescription.appointment.scheduled_at
        )

        elements.append(
            Paragraph(
                (
                    f"<b>Appointment Date:</b> "
                    f"{scheduled_at}"
                ),
                styles["Normal"],
            )
        )

    # ====================================
    # PRESCRIPTION STATUS
    # ====================================

    if prescription.status:
        if hasattr(prescription.status, "value"):
            status_display = (
                prescription.status.value
                .replace("_", " ")
                .title()
            )
        else:
            status_display = (
                str(prescription.status)
                .replace("_", " ")
                .title()
            )
    else:
        status_display = "Unknown"
        

    elements.append(
        Paragraph(
            (
                f"<b>Status:</b> "
                f"{status_display}"
            ),
            styles["Normal"],
        )
    )

    if prescription.status in [
        PrescriptionStatus.SUPERSEDED,
        PrescriptionStatus.LOCKED,
    ]:

        elements.append(
            Spacer(1, 10)
        )

        elements.append(
            Paragraph(
                (
                    "<font color='red'>"
                    "<b>WARNING:</b> "
                    "This prescription revision has been superseded "
                    "by a newer version."
                    "</font>"
                ),
                styles["BodyText"],
            )
        )

        elements.append(
            Spacer(1, 10)
        )

    # ====================================
    # ISSUED TIME
    # ====================================

    if prescription.issued_at:

        issued_at = format_utc(
            prescription.issued_at
        )

        elements.append(
            Paragraph(
                (
                    f"<b>Issued At:</b> "
                    f"{issued_at}"
                ),
                styles["Normal"],
            )
        )

    elements.append(
        Spacer(1, 20)
    )

    # ====================================
    # MEDICINES TABLE
    # ====================================

    if prescription.items:

        data = [[
            "Medicine",
            "Dosage",
            "Frequency",
            "Duration",
            "Instructions",
        ]]

        for item in prescription.items:

            data.append([
                Paragraph(
                    escape(item.medicine_name or ""),
                    styles["BodyText"],
                ),

                Paragraph(
                    escape(item.dosage or ""),
                    styles["BodyText"],
                ),

                Paragraph(
                    escape(item.frequency or ""),
                    styles["BodyText"],
                ),

                Paragraph(
                    str(item.duration_days or ""),
                    styles["BodyText"],
                ),

                Paragraph(
                    escape(item.instructions or ""),
                    styles["BodyText"],
                ),
            ])

        table = Table(
            data,
            repeatRows=1,
            splitByRow=True,
            colWidths=[120, 70, 90, 70, 160],
        )

        table.setStyle(
            TableStyle([
                # Header background
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),

                # Header text
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),

                # Grid
                ("GRID", (0, 0), (-1, -1), 1, colors.black),

                # Header font
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),

                # Header padding
                ("BOTTOMPADDING", (0, 0), (-1, 0), 10),

                # Body background
                ("BACKGROUND", (0, 1), (-1, -1), colors.whitesmoke),

                # Vertical alignment
                ("VALIGN", (0, 0), (-1, -1), "TOP"),

                # Cell padding
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ])
        )

        elements.append(table)

    else:

        elements.append(
            Paragraph(
                "No medicines prescribed.",
                styles["BodyText"],
            )
        )

    elements.append(
        Spacer(1, 20)
    )

    # ====================================
    # NOTES
    # ====================================

    if prescription.notes:

        elements.append(
            Paragraph(
                (
                    f"<b>Notes:</b> "
                    f"{escape(prescription.notes)}"
                ),
                styles["Normal"],
            )
        )

    elements.append(
        Spacer(1, 30)
    )

    # ====================================
    # QR VERIFICATION
    # ====================================

    verification_url = (
        build_prescription_verification_url(
            str(prescription.uuid)
        )
    )

    qr_buffer = generate_qr_code(
        verification_url
    )

    qr_image = Image(
        qr_buffer,
        width=120,
        height=120,
    )

    elements.append(
        Spacer(1, 20)
    )

    elements.append(
        Paragraph(
            (
                "<b>Prescription Verification</b><br/>"
                "Scan QR code to verify authenticity."
            ),
            styles["Normal"],
        )
    )

    elements.append(
        Spacer(1, 10)
    )

    elements.append(qr_image)

    elements.append(
        Spacer(1, 20)
    )

    # ====================================
    # DISCLAIMER
    # ====================================

    elements.append(
        Paragraph(
            (
                "Follow the prescribed dosage carefully. "
                "Consult your doctor before stopping medication."
            ),
            styles["BodyText"],
        )
    )

    elements.append(
        Spacer(1, 30)
    )

    # ====================================
    # SIGNATURE
    # ====================================

    elements.append(
    Spacer(1, 20)
    )

    if (
        prescription.doctor
        and prescription.doctor.signature_file_path
    ):
        storage = get_storage()
        signature_key = prescription.doctor.signature_file_path

        if storage.exists(signature_key):

            # Uploads are decode-checked now, but files predating that check
            # (or corrupted on disk) must not take the whole prescription down
            # with them. An unsigned prescription beats a 500 on a clinical
            # path — the doctor's printed name still follows either way.
            #
            # reportlab's Image is lazy: it only reads the file during
            # doc.build(), so wrapping the constructor catches nothing. The
            # bytes have to be checked here instead.
            signature_bytes: bytes | None = None
            try:
                signature_bytes = storage.read(signature_key)
                ensure_decodable_image(signature_bytes)
            except (ValueError, OSError):
                signature_bytes = None
                logger.warning(
                    "prescription_pdf_signature_unreadable",
                    extra={
                        "prescription_id": prescription.id,
                        "signature_key": signature_key,
                    },
                )

            signature_ok = signature_bytes is not None

            if signature_ok:
                elements.append(
                    Paragraph(
                        "Doctor Signature:",
                        styles["Normal"],
                    )
                )

                elements.append(
                    Spacer(1, 10)
                )

                # Fed from bytes rather than a path so this works unchanged
                # once storage is remote. reportlab's Image is lazy and keeps
                # a reference to the buffer until doc.build() runs, so the
                # BytesIO must not be closed here.
                elements.append(
                    Image(
                        BytesIO(signature_bytes),
                        width=160,
                        height=60,
                    )
                )

                elements.append(
                    Spacer(1, 5)
                )

    elements.append(
        Paragraph(
            escape(doctor_name),
            styles["Normal"],
        )
    )

    elements.append(
        Spacer(1, 20)
    )

    # ====================================
    # FOOTER
    # ====================================

    elements.append(
        Spacer(1, 20)
    )

    footer_text = (
        "This prescription was generated "
        "digitally by HelpDoctor Clinic System."
    )

    if clinic:

        clinic_lines = []

        if clinic.name:
            clinic_lines.append(
                escape(clinic.name)
            )

        if clinic.address:
            clinic_lines.append(
                escape(clinic.address)
            )

        if clinic.phone:
            clinic_lines.append(
                escape(clinic.phone)
            )

        if clinic.email:
            clinic_lines.append(
                escape(clinic.email)
            )

        footer_text += (
            "<br/><br/>"
            + "<br/>".join(clinic_lines)
        )

    elements.append(
        Paragraph(
            footer_text,
            styles["Italic"],
        )
    )
    

    # ====================================
    # BUILD PDF
    # ====================================

    doc.build(
        elements,
        onFirstPage=lambda canvas, doc:
            draw_superseded_watermark(
                canvas,
                doc,
                prescription,
            ),
        onLaterPages=lambda canvas, doc:
            draw_superseded_watermark(
                canvas,
                doc,
                prescription,
            ),
    )

    pdf = buffer.getvalue()

    buffer.close()

    return pdf