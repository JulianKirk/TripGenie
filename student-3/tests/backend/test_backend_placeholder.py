from student3_backend_service import __doc__


def test_backend_package_imports() -> None:
    assert isinstance(__doc__, str)
    assert "Student 3 backend service package." in __doc__
