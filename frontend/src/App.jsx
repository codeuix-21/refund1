import { useRef, useState, useEffect } from 'react';
import MessageList from './components/MessageList.jsx';
import ErrorBanner from './components/ErrorBanner.jsx';
import Composer from './components/Composer.jsx';
import { sendMessage, fetchRefunds, resetSession, resetAllRefunds } from './services/chatService.js';
import RefundTimeline from './components/RefundTimeline.jsx';
import ActiveReturnCard from './components/ActiveReturnCard.jsx';
import OrderHistoryPage from './components/OrderHistoryPage.jsx';
import RefundStatusPage from './components/RefundStatusPage.jsx';
import RefundCelebrationModal from './components/RefundCelebrationModal.jsx';

const newId = () => `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

export default function App() {
  const [currentTab, setCurrentTab] = useState('chat'); // 'chat' | 'orders' | 'refunds'
  const [customerId] = useState('CUS-001');
  const [messages, setMessages] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [demoStep, setDemoStep] = useState(0);
  const [activeReturn, setActiveReturn] = useState(null);
  const [celebrationData, setCelebrationData] = useState(null);

  const initialLoadRef = useRef(true);
  const knownCreditedIdsRef = useRef(new Set());
  const stepTimerRef = useRef(null);

  // Every time localhost is opened again from start, reset previous refunds & database
  useEffect(() => {
    resetAllRefunds();
  }, []);

  // Background poller for refunds to detect newly credited returns
  useEffect(() => {
    let isMounted = true;

    async function checkRefunds() {
      try {
        const data = await fetchRefunds(customerId);
        if (!isMounted || !data.refunds) return;

        // On initial load, record any already-credited returns so we don't spam popups
        if (initialLoadRef.current) {
          data.refunds.forEach((r) => {
            if (r.refund?.status === 'CREDITED' || r.status === 'COMPLETED') {
              knownCreditedIdsRef.current.add(r.return_id);
            }
          });
          initialLoadRef.current = false;
          return;
        }

        // Check for newly credited returns
        for (const item of data.refunds) {
          const isCredited = item.refund?.status === 'CREDITED' || item.status === 'COMPLETED';
          if (isCredited && !knownCreditedIdsRef.current.has(item.return_id)) {
            knownCreditedIdsRef.current.add(item.return_id);

            // Trigger the celebration popup at 12s when step 5 is credited!
            setCelebrationData({
              return_id: item.return_id,
              product_name: item.product_name,
              amount: item.refund?.amount,
              method: item.refund?.method,
            });

            setDemoStep(5);

            // Add notification to chat
            setMessages((prev) => [
              ...prev,
              {
                id: newId(),
                role: 'assistant',
                content: `🎉 **Notification**: Refund of ₹${(item.refund?.amount || 0).toLocaleString('en-IN')} for **${item.product_name}** (${item.return_id}) has been successfully credited to your designated account!`,
                source: 'live',
              },
            ]);
            break;
          }
        }
      } catch (err) {
        // Silent background polling errors
      }
    }

    checkRefunds();
    const interval = setInterval(checkRefunds, 1000);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, [customerId, activeReturn]);

  // Clean up timer on unmount
  useEffect(() => {
    return () => {
      if (stepTimerRef.current) clearInterval(stepTimerRef.current);
    };
  }, []);

  async function requestReply(history) {
    setIsLoading(true);
    setError(null);
    try {
      const reply = await sendMessage(
        history.map(({ role, content }) => ({ role, content })),
        customerId
      );

      setMessages((prev) => [
        ...prev,
        {
          id: newId(),
          role: 'assistant',
          content: reply.text,
          visual_items: reply.visual_items,
          options: reply.options,
          return_created: reply.return_created,
          source: reply.source,
        },
      ]);

      // If a return was just approved ("when I say yes")
      if (reply.return_created) {
        setActiveReturn(reply.return_created);
        setDemoStep(1); // Step 1: Requested

        if (stepTimerRef.current) {
          clearInterval(stepTimerRef.current);
        }

        // Dynamic 5-step progression: 3 seconds per step (total 12 seconds)
        // t=0s: Step 1 (Requested)
        // t=3s: Step 2 (Pickup Booked)
        // t=6s: Step 3 (Quality Check)
        // t=9s: Step 4 (Refund Initiated)
        // t=12s: Step 5 (Bank Credit)
        let stepCount = 1;
        stepTimerRef.current = setInterval(() => {
          stepCount += 1;
          if (stepCount <= 5) {
            setDemoStep(stepCount);
          }
          if (stepCount >= 5) {
            clearInterval(stepTimerRef.current);
            stepTimerRef.current = null;
          }
        }, 5000);
      }
    } catch (err) {
      console.error(err);
      setError('Unable to reach the assistant server. Please check that the server is running.');
    } finally {
      setIsLoading(false);
    }
  }

  function handleSend(text) {
    const trimmed = text.trim();
    if (!trimmed || isLoading) return;
    const next = [...messages, { id: newId(), role: 'user', content: trimmed }];
    setMessages(next);
    requestReply(next);
  }

  function handleRetry() {
    if (!isLoading) requestReply(messages);
  }

  function handleReset() {
    resetSession();
    setMessages([]);
    setError(null);
    setIsLoading(false);
    setDemoStep(0);
    setActiveReturn(null);
    if (stepTimerRef.current) {
      clearInterval(stepTimerRef.current);
      stepTimerRef.current = null;
    }
  }

  function handleReturnItemFromHistory(item) {
    setCurrentTab('chat');
    const promptText = `I want to return ${item.product_name} from order ${item.order_id}`;
    const next = [...messages, { id: newId(), role: 'user', content: promptText }];
    setMessages(next);
    requestReply(next);
  }

  return (
    <div className="app">
      {/* Top Navigation Bar: Leftmost Profile, Center Browser Tabs, Rightmost Actions */}
      <header className="browser-header">
        {/* Leftmost: Customer Information (Profile Picture & Name only - No Customer ID) */}
        <div className="customer-profile">
          <div className="customer-profile__avatar">
            <span>AS</span>
          </div>
          <div className="customer-profile__meta">
            <span className="customer-profile__name">Aarav Sharma</span>
            <span className="customer-profile__badge">
              <span className="status-dot"></span> Verified Customer
            </span>
          </div>
        </div>

        {/* Center / Top: Browser-like Tabs (Small, sleek, clean titles) */}
        <nav className="browser-tabs">
          <button
            type="button"
            className={`browser-tab ${currentTab === 'chat' ? 'browser-tab--active' : ''}`}
            onClick={() => setCurrentTab('chat')}
          >
            <span className="browser-tab__icon">💬</span>
            <span className="browser-tab__label">Return Assistant</span>
          </button>
          <button
            type="button"
            className={`browser-tab ${currentTab === 'orders' ? 'browser-tab--active' : ''}`}
            onClick={() => setCurrentTab('orders')}
          >
            <span className="browser-tab__icon">📦</span>
            <span className="browser-tab__label">Order History</span>
          </button>
          <button
            type="button"
            className={`browser-tab ${currentTab === 'refunds' ? 'browser-tab--active' : ''}`}
            onClick={() => setCurrentTab('refunds')}
          >
            <span className="browser-tab__icon">💳</span>
            <span className="browser-tab__label">Refund Status</span>
          </button>
        </nav>

        {/* Rightmost: Actions */}
        <div className="browser-actions">
          {currentTab === 'chat' && (
            <button
              type="button"
              className="btn-new-chat"
              onClick={handleReset}
              disabled={messages.length === 0}
              title="Start a new chat"
            >
              <span style={{ fontSize: '1.1rem', lineHeight: 1 }}>+</span> New Chat
            </button>
          )}
        </div>
      </header>

      {/* Main Tab Content */}
      {currentTab === 'chat' && (
        <div className="chat-layout">
          <main className="chat-main">
            <MessageList messages={messages} isLoading={isLoading} onPrompt={handleSend} />
            {error && <ErrorBanner message={error} onRetry={handleRetry} />}
            <Composer onSend={handleSend} disabled={isLoading} />
            <p className="disclaimer">
              Powered by Qwen shopping assistant &bull; Fast, direct returns &bull; Press Enter to send
            </p>
          </main>

          <aside className="chat-sidebar">
            <ActiveReturnCard activeReturn={activeReturn} currentStep={demoStep} />
            <RefundTimeline currentStep={demoStep} />
          </aside>
        </div>
      )}

      {currentTab === 'orders' && (
        <OrderHistoryPage
          customerId={customerId}
          onReturnItem={handleReturnItemFromHistory}
        />
      )}

      {currentTab === 'refunds' && (
        <RefundStatusPage
          customerId={customerId}
        />
      )}

      {/* Pop-up Celebration Modal when Refund is Credited at 12s */}
      <RefundCelebrationModal
        open={Boolean(celebrationData)}
        details={celebrationData}
        onClose={() => setCelebrationData(null)}
        onViewRefunds={() => {
          setCelebrationData(null);
          setCurrentTab('refunds');
        }}
      />
    </div>
  );
}
