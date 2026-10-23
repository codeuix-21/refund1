
from datetime import date, datetime, timezone
from uuid import uuid4

from database.db import get_db


ACTIVE_RESERVATION_STATUSES = ("REQUESTED", "APPROVED", "COMPLETED")


class ReturnError(Exception):
    """Expected business-rule error during a return operation."""


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix):
    return f"{prefix}-{uuid4().hex[:12].upper()}"


def check_eligibility(
    connection,
    customer_id,
    order_item_id,
    quantity,
    exclude_return_id=None,
):
    """Validate ownership, delivery, return policy and remaining quantity."""

    if quantity <= 0:
        raise ReturnError("Quantity must be greater than zero.")

    item = connection.execute(
        """
        SELECT
            oi.order_item_id,
            oi.quantity AS purchased_quantity,
            oi.unit_price_paise,
            o.order_id,
            o.customer_id,
            o.status AS order_status,
            o.delivery_date,
            p.product_id,
            p.name AS product_name,
            p.return_window_days,
            p.is_returnable
        FROM order_items oi
        JOIN orders o ON o.order_id = oi.order_id
        JOIN products p ON p.product_id = oi.product_id
        WHERE oi.order_item_id = ?
        """,
        (order_item_id,),
    ).fetchone()

    if item is None:
        raise ReturnError("Order item not found.")

    if item["customer_id"] != customer_id:
        raise ReturnError("This order item does not belong to this customer.")

    if item["order_status"] != "DELIVERED":
        raise ReturnError("Only delivered orders can be returned.")

    if not item["is_returnable"]:
        raise ReturnError("This product is not eligible for return.")

    if not item["delivery_date"]:
        raise ReturnError("Delivery date is unavailable.")

    delivered = date.fromisoformat(item["delivery_date"])
    today = date.today()
    days_since_delivery = (today - delivered).days

    if days_since_delivery < 0:
        raise ReturnError("Delivery date is in the future.")

    if days_since_delivery > item["return_window_days"]:
        raise ReturnError("The return window for this product has expired.")

    reserved = connection.execute(
        """
        SELECT COALESCE(SUM(quantity), 0)
        FROM returns
        WHERE order_item_id = ?
          AND status IN ('REQUESTED', 'APPROVED', 'COMPLETED')
          AND (? IS NULL OR return_id != ?)
        """,
        (
            order_item_id,
            exclude_return_id,
            exclude_return_id,
        ),
    ).fetchone()[0]

    remaining = item["purchased_quantity"] - reserved

    if quantity > remaining:
        raise ReturnError(
            f"Only {remaining} unit(s) remain available for return."
        )

    return {
        "order_id": item["order_id"],
        "order_item_id": item["order_item_id"],
        "product_id": item["product_id"],
        "product_name": item["product_name"],
        "quantity": quantity,
        "remaining_quantity": remaining,
        "unit_price_paise": item["unit_price_paise"],
        "refund_amount_paise": item["unit_price_paise"] * quantity,
        "delivery_date": item["delivery_date"],
        "return_window_days": item["return_window_days"],
    }


def log_event(
    connection,
    return_id,
    event_type,
    description,
    from_status=None,
    to_status=None,
):
    connection.execute(
        """
        INSERT INTO return_events (
            return_id,
            event_type,
            from_status,
            to_status,
            description,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            return_id,
            event_type,
            from_status,
            to_status,
            description,
            utc_now(),
        ),
    )


def create_return(
    customer_id,
    order_item_id,
    quantity,
    reason,
    approval_confirmed=False,
):
    """
    Create a return request.

    If approval_confirmed is True, approve it immediately and
    create its initial pickup and pending refund records.
    """

    allowed_reasons = {
        "DEFECTIVE",
        "WRONG_ITEM",
        "DAMAGED",
        "SIZE_ISSUE",
        "NO_LONGER_NEEDED",
    }

    if reason not in allowed_reasons:
        raise ReturnError("Invalid return reason.")

    return_id = new_id("RET")
    pickup_id = new_id("PICKUP")
    refund_id = new_id("REFUND")
    timestamp = utc_now()

    with get_db() as connection:
        # Acquire the write reservation before checking quantities.
        # This prevents two concurrent requests from reserving
        # the same remaining units.
        connection.execute("BEGIN IMMEDIATE")

        eligibility = check_eligibility(
            connection,
            customer_id,
            order_item_id,
            quantity,
        )

        order = connection.execute(
            """
            SELECT payment_method
            FROM orders
            WHERE order_id = ?
            """,
            (eligibility["order_id"],),
        ).fetchone()

        if order is None:
            raise ReturnError("Order not found.")

        status = "APPROVED" if approval_confirmed else "REQUESTED"
        approved_at = timestamp if approval_confirmed else None

        connection.execute(
            """
            INSERT INTO returns (
                return_id,
                order_item_id,
                quantity,
                reason,
                status,
                requested_at,
                approved_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                return_id,
                order_item_id,
                quantity,
                reason,
                status,
                timestamp,
                approved_at,
            ),
        )

        log_event(
            connection,
            return_id,
            "RETURN",
            "Return request created.",
            None,
            status,
        )

        if approval_confirmed:
            connection.execute(
                """
                INSERT INTO pickups (
                    pickup_id,
                    return_id,
                    status,
                    scheduled_at,
                    created_at
                )
                VALUES (?, ?, 'SCHEDULED', ?, ?)
                """,
                (pickup_id, return_id, timestamp, timestamp),
            )

            connection.execute(
                """
                INSERT INTO refunds (
                    refund_id,
                    return_id,
                    amount_paise,
                    method,
                    status
                )
                VALUES (?, ?, ?, ?, 'PENDING')
                """,
                (
                    refund_id,
                    return_id,
                    eligibility["refund_amount_paise"],
                    order["payment_method"],
                ),
            )

            log_event(
                connection,
                return_id,
                "PICKUP",
                "Pickup scheduled for demo processing.",
                None,
                "SCHEDULED",
            )

            log_event(
                connection,
                return_id,
                "REFUND",
                "Refund record created; awaiting item receipt.",
                None,
                "PENDING",
            )

    return {
        "return_id": return_id,
        "status": status,
        "pickup_id": pickup_id if approval_confirmed else None,
        "refund_id": refund_id if approval_confirmed else None,
        **eligibility,
    }
