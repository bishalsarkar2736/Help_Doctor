# System Architecture – Help_Doctor Backend

This document defines the **current frozen architecture** of the Help_Doctor backend.
It serves as a reference for developers to avoid ambiguity around entity ownership,
ID usage, relationships, and business rules.

Future features may extend this system, but **existing contracts must not be broken**.

---

## 1. Core Entities

### 1.1 User
Represents an authenticated system account.

**Table:** `users`

**Key Fields:**
- `id` (PK) → **users.id**
- `email`
- `hashed_password`
- `role` (`ADMIN | DOCTOR | PATIENT`)
- `is_active`

**Notes:**
- Every actor in the system is a User.
- Doctors are Users with role `DOCTOR`.

---

### 1.2 Doctor
Represents a medical professional profile.

**Table:** `doctors`

**Key Fields:**
- `id` (PK) → **doctors.id**
- `user_id` (FK) → **users.id**
- `specialization`
- `experience_years`
- `bio`

**Rules:**
- `doctors.user_id` is a **1–1 relationship** with `users.id`
- Business logic should treat `Doctor` as a profile, **not an identity**

---

### 1.3 Appointment
Represents a scheduled interaction between a doctor and a patient.

**Table:** `appointments`

**Key Fields:**
- `id` (PK) → **appointments.id**
- `doctor_id` (FK) → **doctors.id**
- `patient_id` (FK) → **users.id**
- `scheduled_at`
- `status`
- `cancelled_at`
- `cancelled_by` → **users.id**
- `cancel_reason`



**Critical Rule:**
- `doctor_id` ≠ `user_id`
- To notify or audit a doctor, resolve:

    appointment.doctor_id  →  Doctor.id  
    Doctor.user_id         →  User.id

more clearly:

Doctor doctor = db.get(Doctor, appointment.doctor_id)
doctor_user_id = doctor.user_id




---

### 1.4 Notification
Represents an audit-safe system notification.

**Table:** `notifications`

**Key Fields:**
- `id` (PK)
- `user_id` (FK) → **users.id**
- `title`
- `message`
- `related_appointment_id` → **appointments.id**
- `created_at`

**Notification Targeting Rule (STRICT):**
> Notifications are ALWAYS sent to **users.id**

❌ Never send notifications to:
- `doctors.id`
- `appointments.doctor_id`

✅ Always resolve to:
- Patient → `appointment.patient_id`
- Doctor → `appointment.doctor.user_id`
- Admin → `admin_user.id`

---

## 2. Entity Relationships (Summary)

User (users)
├── Doctor (doctors.user_id)
├── Appointment.patient_id
├── Appointment.cancelled_by
└── Notification.user_id

Doctor (doctors)
└── Appointment.doctor_id

Appointment (appointments)
└── Notification.related_appointment_id




---

## 3. Appointment Lifecycle

### 3.1 Valid Statuses
- `PENDING`
- `CONFIRMED`
- `COMPLETED`
- `NO_SHOW`
- `CANCELLED`

### 3.2 Typical Flows
### 3.2 Valid Transitions

Patient:
PENDING → CANCELLED

Doctor:
PENDING → CONFIRMED → COMPLETED

System Job:
CONFIRMED → NO_SHOW

Admin:
ANY (except COMPLETED) → CANCELLED


---

## 4. Service Layer Responsibilities

### Services
- `appointment_service.py`
- `appointment_status_service.py`
- `notification_service.py`

**Rules:**
- Services contain business logic
- Routes only orchestrate requests
- Models contain no business logic

---

## 5. Design Constraints (Frozen Rules)

The following rules MUST remain true:

1. Notifications always reference `users.id`
2. Doctors are not users; they reference users
3. Status transitions are validated in services
4. Admin actions are auditable
5. Async DB access only (`AsyncSession`)

---

## 6. Extensibility Notes (Future-Proofing)

The architecture allows future features such as:
- Payments
- Reviews
- Prescriptions
- Chat
- Availability schedules
- Multi-clinic support

These features MUST:
- Reuse existing User identity
- Not overload Appointment responsibility
- Introduce new tables instead of modifying core meaning

---

## 7. Testing Guarantee

Any architectural change must:
- Preserve existing tests
- Add new tests for new behavior
- Never weaken authorization boundaries



## 8. Transaction Strategy

- All database operations use AsyncSession
- Services must not call commit() directly
- Tests use nested SAVEPOINT transactions
- flush() is preferred over commit() in services
- Transaction boundaries are controlled by the request layer

This prevents cross-session FK violations and async loop issues.