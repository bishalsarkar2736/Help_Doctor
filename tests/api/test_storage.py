"""The storage seam.

This refactor is only safe if LocalFilesystemStorage does exactly what the
inline Path(...).write_bytes() calls did before — same keys, same bytes, same
locations — so the tests assert that equivalence rather than just that the
methods exist.
"""

import pytest

from app.services.storage import (
    LocalFilesystemStorage,
    Storage,
    get_storage,
    set_storage,
)


@pytest.fixture
def storage(tmp_path):
    return LocalFilesystemStorage(root=tmp_path)


def test_round_trips_bytes_unchanged(storage):
    data = b"\x89PNG\r\n\x1a\n" + b"payload"
    storage.write("uploads/clinic_logos/x.png", data)
    assert storage.read("uploads/clinic_logos/x.png") == data


def test_write_returns_the_key_that_gets_persisted(storage):
    key = "uploads/doctor_documents/doctor1_bmdc_ab.pdf"
    assert storage.write(key, b"pdf") == key


def test_creates_intermediate_directories(storage, tmp_path):
    """The services used to mkdir(parents=True) themselves."""

    storage.write("media/signatures/doctor_9.png", b"x")
    assert (tmp_path / "media" / "signatures" / "doctor_9.png").is_file()


def test_key_maps_to_the_same_relative_path_as_before(storage, tmp_path):
    """Keys are the paths already stored in the database — not a new scheme.

    If this changes, every existing doctor_documents.file_path and
    doctors.signature_file_path row silently stops resolving.
    """
    storage.write("uploads/doctor_documents/doc.pdf", b"x")
    assert (tmp_path / "uploads/doctor_documents/doc.pdf").read_bytes() == b"x"


def test_exists_reports_accurately(storage):
    assert storage.exists("media/signatures/nope.png") is False
    storage.write("media/signatures/yes.png", b"x")
    assert storage.exists("media/signatures/yes.png") is True


def test_delete_is_idempotent(storage):
    """Replacing a document deletes the previous file, which may already be gone."""

    storage.write("uploads/doctor_documents/old.pdf", b"x")
    storage.delete("uploads/doctor_documents/old.pdf")
    storage.delete("uploads/doctor_documents/old.pdf")  # must not raise
    assert storage.exists("uploads/doctor_documents/old.pdf") is False


def test_read_of_a_missing_key_raises_filenotfound(storage):
    with pytest.raises(FileNotFoundError):
        storage.read("uploads/clinic_logos/missing.png")


@pytest.mark.parametrize(
    "key",
    [
        "../../etc/passwd",
        "uploads/../../etc/passwd",
        "/etc/passwd",
    ],
)
def test_keys_cannot_escape_the_storage_root(storage, key):
    """Keys come back out of the database, so they are not fully trusted."""

    with pytest.raises(ValueError):
        storage.read(key)


def test_local_path_is_inside_the_root(storage, tmp_path):
    path = storage.local_path("media/signatures/doctor_1.png")
    assert path is not None
    assert path.is_relative_to(tmp_path)


def test_get_storage_is_a_singleton():
    set_storage(None)
    try:
        assert get_storage() is get_storage()
    finally:
        set_storage(None)


def test_set_storage_swaps_the_backend(tmp_path):
    replacement = LocalFilesystemStorage(root=tmp_path)
    set_storage(replacement)
    try:
        assert get_storage() is replacement
    finally:
        set_storage(None)


def test_local_filesystem_storage_satisfies_the_protocol(storage):
    assert isinstance(storage, Storage)
