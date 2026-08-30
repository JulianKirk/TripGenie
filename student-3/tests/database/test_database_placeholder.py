from student3_database_service import __doc__


def test_database_package_imports() -> None:
    assert isinstance(__doc__, str)
    assert "Student 3 database service package." in __doc__
