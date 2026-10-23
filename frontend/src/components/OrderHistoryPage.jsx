import { useState, useEffect } from 'react';
import { fetchOrders } from '../services/chatService.js';

export default function OrderHistoryPage({ customerId = 'CUS-001', onReturnItem }) {
    const [orders, setOrders] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [filter, setFilter] = useState('');

    async function load() {
        setLoading(true);
        setError(null);
        try {
            const data = await fetchOrders(customerId);
            setOrders(data.orders || []);
        } catch (err) {
            setError(err.message || 'Failed to load order history');
        } finally {
            setLoading(false);
        }
    }

    useEffect(() => {
        load();
    }, [customerId]);

    const filteredOrders = orders.filter((o) => {
        if (!filter.trim()) return true;
        const query = filter.toLowerCase();
        if (o.order_id.toLowerCase().includes(query)) return true;
        return o.items.some((i) =>
            i.product_name.toLowerCase().includes(query) ||
            (i.brand && i.brand.toLowerCase().includes(query))
        );
    });

    return (
        <div className="store-page">
            <div className="store-page__header">
                <div>
                    <h2 className="store-page__title">Order History</h2>
                    <p className="store-page__sub">
                        Showing past orders and delivered purchases for <strong>Aarav Sharma</strong>.
                    </p>
                </div>
                <div style={{ display: 'flex', gap: '8px' }}>
                    <input
                        type="text"
                        className="store-search-input"
                        placeholder="Search product or order ID..."
                        value={filter}
                        onChange={(e) => setFilter(e.target.value)}
                    />
                    <button type="button" className="btn btn--secondary" onClick={load} disabled={loading}>
                        {loading ? 'Refreshing...' : 'Refresh'}
                    </button>
                </div>
            </div>

            {error && (
                <div className="error-banner" style={{ marginBottom: '16px' }}>
                    <span>{error}</span>
                    <button type="button" className="btn btn--small" onClick={load}>Retry</button>
                </div>
            )}

            {loading && orders.length === 0 ? (
                <div className="store-page__loading">Loading order records from store database...</div>
            ) : filteredOrders.length === 0 ? (
                <div className="store-page__empty">No orders found matching your search.</div>
            ) : (
                <div className="order-list">
                    {filteredOrders.map((order) => (
                        <div key={order.order_id} className="order-card">
                            <div className="order-card__header">
                                <div className="order-card__meta">
                                    <span className="order-card__id">{order.order_id}</span>
                                    <span className="order-card__date">Ordered: {order.order_date}</span>
                                    {order.delivery_date && (
                                        <span className="order-card__delivery">Delivered: {order.delivery_date}</span>
                                    )}
                                </div>
                                <div className="order-card__status-pill">
                                    <span className={`pill ${order.status === 'DELIVERED' ? 'pill--green' : 'pill--gray'}`}>
                                        {order.status}
                                    </span>
                                </div>
                            </div>

                            <div className="order-card__items">
                                {order.items.map((item) => {
                                    const hasCompletedReturn = item.return_status === 'COMPLETED';
                                    const hasActiveReturn = item.return_status === 'APPROVED';

                                    return (
                                        <div key={item.order_item_id} className="order-item-row">
                                            <div className="order-item-row__info">
                                                <div className="order-item-row__name">{item.product_name}</div>
                                                <div className="order-item-row__sub">
                                                    {item.brand && <span>{item.brand} • </span>}
                                                    {item.category && <span>{item.category} • </span>}
                                                    <span>Qty: {item.quantity}</span>
                                                </div>
                                            </div>

                                            <div className="order-item-row__price">
                                                ₹{item.price.toLocaleString('en-IN')}
                                            </div>

                                            <div className="order-item-row__action">
                                                {hasCompletedReturn ? (
                                                    <span className="badge badge--success">
                                                        ✓ Returned (₹{item.price} Credited)
                                                    </span>
                                                ) : hasActiveReturn ? (
                                                    <span className="badge badge--warning">
                                                        ⏳ Return in Progress
                                                    </span>
                                                ) : item.is_returnable ? (
                                                    <button
                                                        type="button"
                                                        className="btn btn--small-primary"
                                                        onClick={() => onReturnItem && onReturnItem(item)}
                                                    >
                                                        Return Item
                                                    </button>
                                                ) : (
                                                    <span className="badge badge--muted">Non-returnable</span>
                                                )}
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}
