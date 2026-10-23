export default function ActiveReturnCard({ activeReturn, currentStep = 0 }) {
  if (!activeReturn) {
    return (
      <section className="card active-return-card active-return-card--empty" aria-label="Return Details">
        <h2 className="card__title">Return Details</h2>
        <div className="empty-return-box">
          <div className="empty-return-icon">📦</div>
          <p className="empty-return-title">No returns requested</p>
          <p className="empty-return-sub">When you approve a return, details of the item will appear here.</p>
        </div>
      </section>
    );
  }

  const productName = activeReturn.product_name || 'Returned Product';
  const orderId = activeReturn.order_id || 'N/A';
  const returnId = activeReturn.return_id || 'N/A';
  const refundAmount = activeReturn.refund_amount != null
    ? activeReturn.refund_amount
    : (activeReturn.refund?.amount_paise ? activeReturn.refund.amount_paise / 100 : 0);
  const refundMethod = activeReturn.refund_method || activeReturn.refund?.method || 'BANK_CARD';
  const isStoreCredit = refundMethod === 'STORE_CREDIT';
  const pickupId = activeReturn.pickup_id || activeReturn.pickup?.pickup_id;

  const isCompleted = currentStep === 5 || activeReturn.status === 'COMPLETED';

  return (
    <section className="card active-return-card" aria-label="Return Details">
      <div className="active-return-header">
        <h2 className="card__title">Return Details</h2>
        <span className={`pill ${isCompleted ? 'pill--green' : 'pill--amber'}`}>
          {isCompleted ? '✓ REFUND CREDITED' : 'PROCESSING'}
        </span>
      </div>

      <div className="active-return-body">
        <div className="active-return-product">
          <div className="active-return-product__icon">📦</div>
          <div className="active-return-product__info">
            <h3 className="active-return-product__name">{productName}</h3>
            <span className="active-return-product__order">Order ID: <strong>{orderId}</strong></span>
          </div>
        </div>

        <div className="active-return-meta">
          <div className="meta-row">
            <span className="meta-label">Return ID</span>
            <code className="meta-code">{returnId}</code>
          </div>
          <div className="meta-row">
            <span className="meta-label">Refund Amount</span>
            <span className="meta-amount">₹{(refundAmount || 0).toLocaleString('en-IN')}</span>
          </div>
          <div className="meta-row">
            <span className="meta-label">Destination</span>
            <span className="meta-val">
              {isStoreCredit ? '🏷️ Store Credit' : '💳 Direct Bank Credit'}
            </span>
          </div>
          {pickupId && (
            <div className="meta-row">
              <span className="meta-label">Courier Pickup</span>
              <code className="meta-code">{pickupId}</code>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
