from app.models.medicine import Medicine



def build_medicine_context(
    medicine: Medicine,
) -> str:

    return f"""
Medicine Name:
{medicine.name}

Generic Name:
{medicine.generic_name}

Strength:
{medicine.strength}

Manufacturer:
{medicine.manufacturer}

Category:
{medicine.category}

Dosage Form:
{medicine.dosage_form}

Common Use:
{medicine.common_use}

Side Effects:
{medicine.common_side_effects}

Storage:
{medicine.storage_guidance}
"""