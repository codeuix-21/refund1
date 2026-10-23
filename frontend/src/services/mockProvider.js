const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// Every event is simulated. "events" is what the Thought Box shows.
const REPLIES = [
    {
        keywords: ['damaged', 'broken', 'defective'],
        text:
            "I'm sorry your item arrived in that condition. To look into it, I'd need to know which item it is and what's wrong with it. " +
            "Please tell me the item name and describe the damage.\n\n(Demo mode: I can't look up real orders or submit anything yet.)",
        events: [
            { type: 'thinking', text: 'Customer reports a damaged item. I need to know which item before checking anything.' },
            { type: 'tool', text: '[Simulated] Would look up the customer\'s recent orders.' },
            { type: 'store', text: '[Simulated] No real store is connected in demo mode.' },
        ],
    },
    {
        keywords: ['refund'],
        text:
            'Generally, a refund is started after a return is approved and the item is received and checked. ' +
            'The money is first marked as "initiated", and later as "credited" once it reaches your bank or store credit. ' +
            'Exact timings depend on the store\'s policy.\n\n(Demo mode: this is a general explanation, not your real refund status.)',
        events: [
            { type: 'thinking', text: 'General refund question. No order lookup needed, so I will explain the process.' },
        ],
    },
    {
        keywords: ['process', 'how', 'understand'],
        text:
            'A typical return works like this:\n1. You request a return and give a reason.\n2. The store checks it against its return policy.\n3. You confirm the details.\n4. A pickup is arranged.\n5. The item is checked, then the refund is started.\n\n(Demo mode: simulated response.)',
        events: [
            { type: 'thinking', text: 'Customer wants an overview of the return process. I will list the steps.' },
        ],
    },
    {
        keywords: ['return'],
        text:
            "Happy to help with a return. Which item would you like to return, and what's the reason?\n\n(Demo mode: I can't submit a real return yet.)",
        events: [
            { type: 'thinking', text: 'Customer wants to start a return. I need the item and the reason first.' },
            { type: 'tool', text: '[Simulated] Would check return eligibility once the item is known.' },
            { type: 'store', text: '[Simulated] No real store is connected in demo mode.' },
        ],
    },
];

const FALLBACK = {
    text:
        "I can help with return and refund questions. Try asking about starting a return, how refunds work, or a damaged item.\n\n(Demo mode: simulated response.)",
    events: [
        { type: 'thinking', text: 'The message is not clearly about returns or refunds. I will suggest what I can help with.' },
    ],
};

// Type "test error" in the chat to trigger the error state.
export async function mockReply(history) {
    await delay(900);
    const last = history[history.length - 1]?.content.toLowerCase() ?? '';

    if (last.includes('test error')) {
        throw new Error('Simulated AI service failure');
    }

    const match = REPLIES.find((r) => r.keywords.some((k) => last.includes(k))) ?? FALLBACK;
    return { text: match.text, events: match.events, source: 'mock' };
}