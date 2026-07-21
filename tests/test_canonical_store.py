try:
    from app.canonical_store import CanonicalModelStore
except ModuleNotFoundError:
    from canonical_store import CanonicalModelStore


def test_canonical_store_attribute_search():
    store = CanonicalModelStore()

    # Test searching for transaction ID
    results = store.search_attributes("txn_id")
    assert len(results) > 0
    top = results[0]
    assert top["target_attribute"] == "AC_TXN_ID"
    assert top["confidence_score"] > 0.7


def test_canonical_store_search_amount():
    store = CanonicalModelStore()
    results = store.search_attributes("amount")
    assert len(results) > 0
    top = results[0]
    assert (
        top["target_attribute"] == "TRANSACTION_AMOUNT"
        or top["target_attribute"] == "CURRENT_BALANCE"
    )
    assert top["confidence_score"] > 0.7
