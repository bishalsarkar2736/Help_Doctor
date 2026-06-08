from io import BytesIO

import qrcode


def generate_qr_code(
    verification_url: str,
) -> BytesIO:

    qr = qrcode.QRCode(
        version=1,
        box_size=8,
        border=2,
    )

    qr.add_data(verification_url)

    qr.make(fit=True)

    image = qr.make_image(
        fill_color="black",
        back_color="white",
    )

    buffer = BytesIO()

    image.save(buffer, format="PNG")

    buffer.seek(0)

    return buffer