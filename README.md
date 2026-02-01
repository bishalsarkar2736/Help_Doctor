# 🏥 Help_Doctor – Backend API

Help_Doctor is a backend service for managing medical appointments, users (admin, doctor, patient), and notifications.  
Built with **FastAPI**, **SQLAlchemy (async)**, and **PostgreSQL/SQLite**, with full **pytest** coverage.

---

## 🚀 Tech Stack

- **Python 3.12**
- **FastAPI**
- **SQLAlchemy (Async ORM)**
- **PostgreSQL / SQLite (for tests)**
- **Alembic** – migrations
- **Pytest + pytest-asyncio**
- **Docker & Docker Compose**

---

## 📁 Project Structure

Help_Doctor/
├── app/
│ ├── models/ # SQLAlchemy models
│ ├── services/ # Business logic (appointments, notifications)
│ ├── db/ # DB session & base
│ └── main.py # FastAPI app
├── tests/
│ ├── test_appointments/
│ └── test_notifications/
├── alembic/ # DB migrations
├── docker-compose.yml
├── Dockerfile
├── pytest.ini
├── run.py
└── README.md


---

## ⚙️ Local Setup (Without Docker)

### 1️⃣ Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/Help_Doctor.git
cd Help_Doctor

Create & activate virtual environment
python3 -m venv venv
source venv/bin/activate

Install dependencies
pip install -r requirements.txt


If you don’t have requirements.txt:

pip freeze > requirements.txt

Environment variables

Create a .env file:

DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/help_doctor
SECRET_KEY=supersecretkey

Run database migrations
alembic upgrade head


Start the server
uvicorn app.main:app --reload


API will be available at:

http://127.0.0.1:8000


Swagger UI:

http://127.0.0.1:8000/docs

