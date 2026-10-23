import { config } from '../config.js';
import { mockReply } from './mockProvider.js';

let sessionId = typeof window !== 'undefined' ? localStorage.getItem('agent_session_id') : null;
if (!sessionId && typeof window !== 'undefined') {
    sessionId = 'session_' + Math.random().toString(36).substring(2, 10);
    localStorage.setItem('agent_session_id', sessionId);
}

export function resetSession() {
    if (typeof window !== 'undefined') {
        sessionId = 'session_' + Math.random().toString(36).substring(2, 10);
        localStorage.setItem('agent_session_id', sessionId);
    }
}

/**
 * Sends user prompt/message to the real agent API (or mock in demo mode).
 * history: [{ role: 'user' | 'assistant', content: string }]
 */
export async function sendMessage(history, customerId = 'CUS-001') {
    if (config.useMock) {
        return mockReply(history);
    }

    const lastMessage = history[history.length - 1];
    const userText = typeof lastMessage === 'string' ? lastMessage : lastMessage.content;

    const response = await fetch(`${config.apiBaseUrl}/api/chat`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            message: userText,
            session_id: sessionId || 'default',
            customer_id: customerId,
        }),
    });

    if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`API error (${response.status}): ${errorText}`);
    }

    const data = await response.json();
    return {
        text: data.text,
        state: data.state,
        visual_items: data.visual_items || [],
        options: data.options || [],
        return_created: data.return_created || null,
        source: 'live',
    };
}

/**
 * Mock Store Page 1: Fetches full order history for the customer.
 */
export async function fetchOrders(customerId = 'CUS-001') {
    const response = await fetch(`${config.apiBaseUrl}/api/orders?customer_id=${customerId}`);
    if (!response.ok) {
        throw new Error(`Failed to fetch orders (${response.status})`);
    }
    return await response.json();
}

/**
 * Mock Store Page 2: Fetches live returns and refunds tracking.
 */
export async function fetchRefunds(customerId = 'CUS-001') {
    const response = await fetch(`${config.apiBaseUrl}/api/refunds?customer_id=${customerId}`);
    if (!response.ok) {
        throw new Error(`Failed to fetch refunds (${response.status})`);
    }
    return await response.json();
}

/**
 * Resets all return and refund records on the server when opening localhost afresh.
 */
export async function resetAllRefunds() {
    try {
        const response = await fetch(`${config.apiBaseUrl}/api/reset-all`, {
            method: 'POST',
        });
        if (!response.ok) {
            return null;
        }
        return await response.json();
    } catch (err) {
        console.warn('Failed to reset store returns on launch:', err);
        return null;
    }
}
