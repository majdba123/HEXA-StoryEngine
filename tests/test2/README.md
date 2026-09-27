# Test2 owner-layer quality certification

Test2 is rebuilt from the product quality rules rather than copied from historical test
files.  Each rule migrates from runtime QA into exactly one owner layer, receives normal,
boundary, invalid, ambiguous, adversarial, generated and regression coverage, and is
recorded in `quality_rule_ledger.py`.

`test_master_qa.py` is the migration completion gate.  It must not be switched to
`MIGRATION_COMPLETE = True` until every pre-render QA rule is owned by production code,
every declared Test2 module exists, and the legacy runtime QA surfaces are deleted.

`tests/test1/` remains active throughout as independent system-level compatibility and
architecture certification.
