import pytest

from evals.oracle_verifier import oracle_verify

CASES = [
    ({"name": "Margaret Chen", "dob": "1985-03-15", "id_last4": "4472"}, "P9"),
    ({"name": "Margaret Chen", "dob": "1985-03-15"}, None),
    ({"name": "Margaret Chen", "dob": "1985-03-15", "phone": "+16505212830"}, None),
    ({"name": "Yaven Li", "phone": "+16505212830", "email": "yawen.li@example.com"}, "P13"),
    ({"name": "Ma Tian", "dob": "1964-09-10", "id_last4": "6688"}, "P12"),
    ({"policy_number": "POL-9921", "name": "Margaret Chen", "dob": "1985-03-15"}, None),
    ({"policy_number": "POL-1044", "name": "Margaret Chen", "dob": "1985-03-15", "id_last4": "4472"}, None),
]


@pytest.mark.parametrize("factors,expected", CASES)
def test_oracle(repo, factors, expected):
    assert oracle_verify(repo, factors) == expected
