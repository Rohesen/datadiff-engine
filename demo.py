import pandas as pd

from datadiff_engine import DiffConfig, compare


old = pd.DataFrame({
    "customer_id": [1, 2, 3],
    "amount": [100, 200, 300],
})

new = pd.DataFrame({
    "customer_id": [1, 2, 3, 4],
    "amount": [100, 200, None, 500],
    "country": ["IN", "IN", "US", "IN"],
})


config = DiffConfig(
    warning_null_rate=0.10,
    critical_null_rate=0.50,
)

diff = compare(old, new, config=config)

print(diff)
print()

amount = diff.column("amount")

print("COLUMN:", amount.name)
print("Old type:", amount.old_dtype)
print("New type:", amount.new_dtype)
print("Old null rate:", amount.null_rate_old)
print("New null rate:", amount.null_rate_new)
print("Null rate change:", amount.null_rate_change)
print("Type changed:", amount.dtype_changed)
print("Severity:", amount.severity)

print()
print("DICTIONARY REPORT:")
print(diff.to_dict())