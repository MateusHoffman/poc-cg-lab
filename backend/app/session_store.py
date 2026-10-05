from __future__ import annotations

import logging
import time
from decimal import Decimal
from typing import Any

from boto3.dynamodb.conditions import Key
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger("cg.session")

TABLE_NAME = "CG_AutoAgent_Table"


class SessionStore:
    """Single-table design.

    PK = SESSION#<id>
    SK = META | STATE | MSG#<timestamp>
    """

    def __init__(self, endpoint_url: str | None) -> None:
        self.backend = "memory"
        self._items: dict[tuple[str, str], dict] = {}
        self._table = None
        if endpoint_url:
            self._try_dynamo(endpoint_url)

    def _try_dynamo(self, endpoint_url: str) -> None:
        try:
            import boto3

            resource = boto3.resource(
                "dynamodb",
                endpoint_url=endpoint_url,
                region_name="us-east-1",
                aws_access_key_id="mock",
                aws_secret_access_key="mock",
                config=Config(
                    connect_timeout=2,
                    read_timeout=2,
                    retries={"max_attempts": 1},
                ),
            )
            try:
                table = resource.create_table(
                    TableName=TABLE_NAME,
                    KeySchema=[
                        {"AttributeName": "PK", "KeyType": "HASH"},
                        {"AttributeName": "SK", "KeyType": "RANGE"},
                    ],
                    AttributeDefinitions=[
                        {"AttributeName": "PK", "AttributeType": "S"},
                        {"AttributeName": "SK", "AttributeType": "S"},
                    ],
                    BillingMode="PAY_PER_REQUEST",
                )
                table.wait_until_exists()
            except ClientError as exc:
                if exc.response["Error"]["Code"] != "ResourceInUseException":
                    raise
                table = resource.Table(TABLE_NAME)
            self._table = table
            self.backend = "dynamodb"
            logger.info("sessão conectada ao DynamoDB local")
        except (BotoCoreError, ClientError, OSError) as exc:
            logger.warning("DynamoDB indisponível (%s); sessão fica em memória", exc)

    def _put(self, item: dict) -> None:
        if self._table is not None:
            self._table.put_item(Item=item)
            return
        self._items[(item["PK"], item["SK"])] = item

    def save_message(self, session_id: str, role: str, content: str) -> None:
        self._put(
            {
                "PK": f"SESSION#{session_id}",
                "SK": f"MSG#{time.time_ns()}",
                "entity": "message",
                "role": role,
                "content": content,
            }
        )

    def save_state(self, session_id: str, vehicle_ids: list[str], intent: str) -> None:
        self._put(
            {
                "PK": f"SESSION#{session_id}",
                "SK": "STATE",
                "entity": "agent_state",
                "vehicle_ids": vehicle_ids,
                "intent": intent,
            }
        )
        self._put(
            {
                "PK": f"SESSION#{session_id}",
                "SK": "META",
                "entity": "session",
                "updated_at": int(time.time()),
                "last_intent": intent,
            }
        )

    def get_state(self, session_id: str) -> dict[str, Any]:
        pk = f"SESSION#{session_id}"
        if self._table is not None:
            response = self._table.get_item(Key={"PK": pk, "SK": "STATE"})
            return response.get("Item") or {"vehicle_ids": [], "intent": ""}
        return self._items.get((pk, "STATE"), {"vehicle_ids": [], "intent": ""})

    def list_items(self, session_id: str) -> list[dict]:
        pk = f"SESSION#{session_id}"
        if self._table is not None:
            response = self._table.query(KeyConditionExpression=Key("PK").eq(pk))
            return response.get("Items", [])
        return [item for (item_pk, _), item in self._items.items() if item_pk == pk]


def json_ready(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    if isinstance(value, dict):
        return {key: json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_ready(item) for item in value]
    return value
