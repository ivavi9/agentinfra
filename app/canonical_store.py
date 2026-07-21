from typing import List, Dict, Any

CANONICAL_ENTITIES: Dict[str, Dict[str, Any]] = {
    "INDIVIDUAL": {
        "subject_area": "INVOLVED_PARTY",
        "description": "Natural person acting as customer, party, or stakeholder.",
        "attributes": {
            "IP_ID": {
                "type": "VARCHAR(64)",
                "description": "Involved Party unique surrogate key",
                "is_pk": True,
            },
            "FIRST_NAME": {
                "type": "VARCHAR(100)",
                "description": "Given first name of the individual",
                "is_pk": False,
            },
            "LAST_NAME": {
                "type": "VARCHAR(100)",
                "description": "Family surname of the individual",
                "is_pk": False,
            },
            "EMAIL_ADDRESS": {
                "type": "VARCHAR(255)",
                "description": "Primary electronic contact email",
                "is_pk": False,
            },
            "PHONE_NUMBER": {
                "type": "VARCHAR(50)",
                "description": "Primary telephone contact number",
                "is_pk": False,
            },
            "DATE_OF_BIRTH": {
                "type": "DATE",
                "description": "Date of birth of the individual",
                "is_pk": False,
            },
            "TAX_IDENTIFIER_HASH": {
                "type": "VARCHAR(64)",
                "description": "Hashed tax registration identifier",
                "is_pk": False,
            },
        },
    },
    "DEPOSIT_ACCOUNT": {
        "subject_area": "ARRANGEMENT",
        "description": "Financial deposit arrangement or bank account.",
        "attributes": {
            "AC_ID": {
                "type": "VARCHAR(64)",
                "description": "Account arrangement unique surrogate key",
                "is_pk": True,
            },
            "ACCOUNT_NUMBER": {
                "type": "VARCHAR(50)",
                "description": "External bank account identifier",
                "is_pk": False,
            },
            "IP_ID": {
                "type": "VARCHAR(64)",
                "description": "Owner party surrogate key",
                "is_pk": False,
            },
            "ACCOUNT_TYPE": {
                "type": "VARCHAR(50)",
                "description": "Classification of deposit account (e.g. SAVINGS, CHECKING)",
                "is_pk": False,
            },
            "CURRENCY_CODE": {
                "type": "VARCHAR(3)",
                "description": "ISO 4217 currency code",
                "is_pk": False,
            },
            "CURRENT_BALANCE": {
                "type": "NUMERIC(18,2)",
                "description": "Current ledger balance of account",
                "is_pk": False,
            },
            "OPEN_DATE": {
                "type": "DATE",
                "description": "Date account arrangement was opened",
                "is_pk": False,
            },
        },
    },
    "FINANCIAL_TRANSACTION": {
        "subject_area": "FINANCIAL_TRANSACTION",
        "description": "Financial movement, monetary transfer, or ledger transaction.",
        "attributes": {
            "AC_TXN_ID": {
                "type": "VARCHAR(64)",
                "description": "Transaction unique surrogate key",
                "is_pk": True,
            },
            "AC_ID": {
                "type": "VARCHAR(64)",
                "description": "Associated account arrangement surrogate key",
                "is_pk": False,
            },
            "CUSTOMER_ID_HASH": {
                "type": "VARCHAR(64)",
                "description": "Hashed customer/party identifier",
                "is_pk": False,
            },
            "TRANSACTION_AMOUNT": {
                "type": "NUMERIC(18,2)",
                "description": "Monetary value of transaction",
                "is_pk": False,
            },
            "TRANSACTION_TIMESTAMP": {
                "type": "TIMESTAMP",
                "description": "Timestamp when transaction occurred",
                "is_pk": False,
            },
            "TRANSACTION_TYPE": {
                "type": "VARCHAR(50)",
                "description": "Type of transaction (DEBIT, CREDIT, TRANSFER)",
                "is_pk": False,
            },
            "CHANNEL_ID": {
                "type": "VARCHAR(50)",
                "description": "Channel identifier (ATM, ONLINE, BRANCH)",
                "is_pk": False,
            },
        },
    },
}


class CanonicalModelStore:
    """Grounding reference store for enterprise canonical model entities & attributes."""

    def __init__(self):
        self.entities = CANONICAL_ENTITIES

    def _vectorize_text(self, text: str) -> Dict[str, float]:
        """Convert column/attribute string into character n-gram frequency vector."""
        clean = text.lower().replace("_", " ")
        words = clean.split()
        ngrams: Dict[str, float] = {}
        for w in words:
            ngrams[w] = ngrams.get(w, 0.0) + 1.0
            for i in range(len(w) - 2):
                gram = w[i : i + 3]
                ngrams[gram] = ngrams.get(gram, 0.0) + 0.5
        return ngrams

    def _cosine_similarity(
        self, vec1: Dict[str, float], vec2: Dict[str, float]
    ) -> float:
        """Compute cosine similarity between two feature vectors."""
        dot_product = sum(val * vec2[k] for k, val in vec1.items() if k in vec2)
        norm1 = (sum(v * v for v in vec1.values())) ** 0.5
        norm2 = (sum(v * v for v in vec2.values())) ** 0.5
        if not norm1 or not norm2:
            return 0.0
        return dot_product / (norm1 * norm2)

    def search_attributes(
        self, column_name: str, top_k: int = 3
    ) -> List[Dict[str, Any]]:
        """Search canonical store for candidate attributes using vector similarity and domain matching."""
        clean_col = column_name.lower().replace("_", "")
        col_vec = self._vectorize_text(column_name)
        candidates = []

        for entity_name, entity_data in self.entities.items():
            for attr_name, attr_info in entity_data["attributes"].items():
                clean_attr = attr_name.lower().replace("_", "")
                attr_vec = self._vectorize_text(attr_name)

                # Compute vector similarity score
                vec_sim = self._cosine_similarity(col_vec, attr_vec)

                # Compute exact/substring heuristic bonus
                score = round(vec_sim, 2)
                if clean_col == clean_attr:
                    score = 0.98
                elif clean_col in clean_attr or clean_attr in clean_col:
                    score = max(score, 0.85)
                else:
                    if (
                        "amt" in clean_col
                        or "amount" in clean_col
                        or "val" in clean_col
                    ) and ("amount" in clean_attr or "balance" in clean_attr):
                        score = max(score, 0.80)
                    elif (
                        "cust" in clean_col
                        or "user" in clean_col
                        or "party" in clean_col
                    ) and ("ip" in clean_attr or "id" in clean_attr):
                        score = max(score, 0.75)
                    elif (
                        "date" in clean_col
                        or "time" in clean_col
                        or "stamp" in clean_col
                    ) and ("timestamp" in clean_attr or "date" in clean_attr):
                        score = max(score, 0.75)

                if score > 0.3:
                    candidates.append(
                        {
                            "entity": entity_name,
                            "subject_area": entity_data["subject_area"],
                            "target_attribute": attr_name,
                            "data_type": attr_info["type"],
                            "description": attr_info["description"],
                            "confidence_score": score,
                        }
                    )

        candidates.sort(key=lambda x: x["confidence_score"], reverse=True)
        return candidates[:top_k]

    def get_all_entities(self) -> Dict[str, Any]:
        return self.entities
