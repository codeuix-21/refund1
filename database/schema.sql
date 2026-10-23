PRAGMA foreign_keys = ON;

-- 1. Customers
CREATE TABLE IF NOT EXISTS customers (
    customer_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT UNIQUE,
    created_at TEXT NOT NULL
);

-- 2. Products
CREATE TABLE IF NOT EXISTS products (
    product_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    brand TEXT NOT NULL,
    category TEXT NOT NULL,
    aliases TEXT NOT NULL DEFAULT '[]'
        CHECK (json_valid(aliases)),
    return_window_days INTEGER NOT NULL
        CHECK (return_window_days >= 0),
    is_returnable INTEGER NOT NULL
        CHECK (is_returnable IN (0, 1))
);

-- 3. Orders
CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    order_date TEXT NOT NULL,
    delivery_date TEXT,
    status TEXT NOT NULL
        CHECK (status IN (
            'PLACED',
            'SHIPPED',
            'DELIVERED',
            'CANCELLED'
        )),
    payment_method TEXT NOT NULL
        CHECK (payment_method IN (
            'UPI',
            'BANK_CARD',
            'NET_BANKING',
            'WALLET'
        )),
    created_at TEXT NOT NULL,

    FOREIGN KEY (customer_id)
        REFERENCES customers(customer_id),

    CHECK (
        delivery_date IS NULL
        OR delivery_date >= order_date
    ),

    CHECK (
        status != 'DELIVERED'
        OR delivery_date IS NOT NULL
    )
);

-- 4. Items purchased in each order
CREATE TABLE IF NOT EXISTS order_items (
    order_item_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price_paise INTEGER NOT NULL
        CHECK (unit_price_paise >= 0),

    FOREIGN KEY (order_id)
        REFERENCES orders(order_id),

    FOREIGN KEY (product_id)
        REFERENCES products(product_id),

    UNIQUE (order_id, product_id)
);

-- 5. Return requests
CREATE TABLE IF NOT EXISTS returns (
    return_id TEXT PRIMARY KEY,
    order_item_id TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),

    reason TEXT NOT NULL
        CHECK (reason IN (
            'DEFECTIVE',
            'WRONG_ITEM',
            'DAMAGED',
            'SIZE_ISSUE',
            'NO_LONGER_NEEDED'
        )),

    status TEXT NOT NULL DEFAULT 'REQUESTED'
        CHECK (status IN (
            'REQUESTED',
            'APPROVED',
            'REJECTED',
            'CANCELLED',
            'COMPLETED'
        )),

    requested_at TEXT NOT NULL,
    approved_at TEXT,
    completed_at TEXT,

    FOREIGN KEY (order_item_id)
        REFERENCES order_items(order_item_id),

    CHECK (
        status != 'APPROVED'
        OR approved_at IS NOT NULL
    ),

    CHECK (
        status != 'COMPLETED'
        OR completed_at IS NOT NULL
    )
);

-- 6. Pickup attempts
-- A return can have multiple pickup attempts.
-- Failed attempts are preserved instead of overwritten.
CREATE TABLE IF NOT EXISTS pickups (
    pickup_id TEXT PRIMARY KEY,
    return_id TEXT NOT NULL,

    status TEXT NOT NULL DEFAULT 'SCHEDULED'
        CHECK (status IN (
            'SCHEDULED',
            'PICKED_UP',
            'RECEIVED',
            'FAILED',
            'CANCELLED'
        )),

    scheduled_at TEXT,
    picked_up_at TEXT,
    received_at TEXT,
    failure_reason TEXT,
    created_at TEXT NOT NULL,

    FOREIGN KEY (return_id)
        REFERENCES returns(return_id),

    CHECK (
        status != 'PICKED_UP'
        OR picked_up_at IS NOT NULL
    ),

    CHECK (
        status != 'RECEIVED'
        OR received_at IS NOT NULL
    ),

    CHECK (
        status != 'FAILED'
        OR failure_reason IS NOT NULL
    )
);

-- 7. Refund record
-- One refund record per return.
-- Retry failures are retained in return_events.
CREATE TABLE IF NOT EXISTS refunds (
    refund_id TEXT PRIMARY KEY,
    return_id TEXT NOT NULL UNIQUE,

    amount_paise INTEGER NOT NULL
        CHECK (amount_paise >= 0),

    method TEXT NOT NULL
        CHECK (method IN (
            'UPI',
            'BANK_CARD',
            'NET_BANKING',
            'WALLET'
        )),

    status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (status IN (
            'PENDING',
            'INITIATED',
            'CREDITED',
            'FAILED'
        )),

    initiated_at TEXT,
    credited_at TEXT,
    failure_reason TEXT,

    FOREIGN KEY (return_id)
        REFERENCES returns(return_id),

    CHECK (
        (status = 'CREDITED' AND credited_at IS NOT NULL)
        OR
        (status != 'CREDITED' AND credited_at IS NULL)
    ),

    CHECK (
        status != 'FAILED'
        OR failure_reason IS NOT NULL
    )
);

-- 8. Unified event history
CREATE TABLE IF NOT EXISTS return_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    return_id TEXT NOT NULL,

    event_type TEXT NOT NULL
        CHECK (event_type IN (
            'RETURN',
            'PICKUP',
            'REFUND'
        )),

    from_status TEXT,
    to_status TEXT,
    description TEXT NOT NULL,
    created_at TEXT NOT NULL,

    FOREIGN KEY (return_id)
        REFERENCES returns(return_id)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_orders_customer_date
    ON orders(customer_id, order_date);

CREATE INDEX IF NOT EXISTS idx_orders_customer_delivery
    ON orders(customer_id, delivery_date);

CREATE INDEX IF NOT EXISTS idx_order_items_order
    ON order_items(order_id);

CREATE INDEX IF NOT EXISTS idx_returns_item_status
    ON returns(order_item_id, status);

CREATE INDEX IF NOT EXISTS idx_pickups_return_status
    ON pickups(return_id, status);

CREATE INDEX IF NOT EXISTS idx_events_return_time
    ON return_events(return_id, created_at);


-- 9. Monitoring checkpoints
CREATE TABLE IF NOT EXISTS monitoring_checkpoints (
    return_id TEXT PRIMARY KEY,
    last_observed_status TEXT NOT NULL,
    last_event_id INTEGER,
    active_alert_signature TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (return_id) REFERENCES returns(return_id)
);

CREATE INDEX IF NOT EXISTS idx_monitoring_checkpoints_status
    ON monitoring_checkpoints(last_observed_status);


-- 10. Pickup recovery attempts
CREATE TABLE IF NOT EXISTS pickup_attempts (
    attempt_id TEXT PRIMARY KEY,
    pickup_id TEXT NOT NULL,
    return_id TEXT NOT NULL,
    attempt_number INTEGER NOT NULL,
    idempotency_key TEXT UNIQUE NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('PENDING', 'SUCCESS', 'FAILED', 'UNCERTAIN')),
    external_reference TEXT,
    error_details TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY (pickup_id) REFERENCES pickups(pickup_id),
    FOREIGN KEY (return_id) REFERENCES returns(return_id)
);

CREATE INDEX IF NOT EXISTS idx_pickup_attempts_return
    ON pickup_attempts(return_id);

-- 11. Refund initiation attempts
CREATE TABLE IF NOT EXISTS refund_attempts (
    attempt_id TEXT PRIMARY KEY,
    refund_id TEXT NOT NULL,
    return_id TEXT NOT NULL,
    attempt_number INTEGER NOT NULL,
    idempotency_key TEXT UNIQUE NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('PENDING', 'SUCCESS', 'FAILED', 'UNCERTAIN')),
    external_reference TEXT,
    error_details TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY (refund_id) REFERENCES refunds(refund_id),
    FOREIGN KEY (return_id) REFERENCES returns(return_id)
);

CREATE INDEX IF NOT EXISTS idx_refund_attempts_refund
    ON refund_attempts(refund_id);

CREATE INDEX IF NOT EXISTS idx_refund_attempts_return
    ON refund_attempts(return_id);
