export default function OrderSummary({ order }) {
    return (
        <section className="card" aria-label="Order summary">
            <h2 className="card__title">Order summary</h2>
            <p className="card__line">Item: {order.item}</p>
            <p className="card__line">Ordered: {order.date}</p>
            <p className="card__line">Amount: ₹{order.amount.toLocaleString('en-IN')}</p>
        </section>
    );
}
