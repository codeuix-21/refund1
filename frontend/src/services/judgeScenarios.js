// Scripted demo tests for judges. All data is fictional and simulated.
// Later, these can be replaced by real calls to the agent/backend.

export const SCENARIOS = [
    {
        id: 'normal',
        label: 'Test 1: Normal Return',
        userMessage: 'I want to return my Running Shoes. They are defective.',
        reply:
            'Good news: your Running Shoes are within the return window, so they can be returned. ' +
            'Please check the details in the popup and approve to continue.\n\n' +
            '(Demo mode: nothing is booked until you approve, and no real return is created.)',
        events: [
            { type: 'thinking', text: 'Customer wants to return defective Running Shoes. I must check eligibility before proposing anything.' },
            { type: 'tool', text: '[Simulated] check-eligibility for the Running Shoes order item.' },
            { type: 'store', text: '[Simulated] ELIGIBLE: 3 days since delivery, allowed 14 days.' },
            { type: 'thinking', text: 'Eligible. I must get the customer\'s explicit approval before creating a return.' },
        ],
        timelineStep: 0,
        opensApproval: true,
    },
    {
        id: 'expired',
        label: 'Test 2: Expired Return',
        userMessage: 'I want to return my Running Shoes. I got them a month ago.',
        reply:
            "I'm sorry, but these shoes are outside the 14-day return window, so I can't start a return for them.\n\n" +
            '(Demo mode: simulated result.)',
        events: [
            { type: 'thinking', text: 'Customer wants to return an older item. I need to check the return window first.' },
            { type: 'tool', text: '[Simulated] check-eligibility for the Running Shoes order item.' },
            { type: 'store', text: '[Simulated] BLOCKED: 30 days since delivery, allowed 14 days.' },
            { type: 'thinking', text: 'Blocked by policy. I will explain the reason and not create a return.' },
        ],
        timelineStep: 0,
        opensApproval: false,
    },
    {
        id: 'socks',
        label: 'Test 3: Non-Returnable Socks',
        userMessage: 'I want to return my Cotton Socks.',
        reply:
            "I'm sorry, socks are a non-returnable hygiene item under this store's policy, so I can't start a return for them.\n\n" +
            '(Demo mode: simulated result.)',
        events: [
            { type: 'thinking', text: 'Customer wants to return socks. Hygiene items may be excluded, so I will check the policy.' },
            { type: 'tool', text: '[Simulated] check-eligibility for the Cotton Socks order item.' },
            { type: 'store', text: '[Simulated] BLOCKED: policy tag NON_RETURNABLE_HYGIENE.' },
            { type: 'thinking', text: 'Blocked by policy. I will explain it and not create a return.' },
        ],
        timelineStep: 0,
        opensApproval: false,
    },
    {
        id: 'tracking',
        label: 'Test 4: Refund Tracking',
        userMessage: 'Where is my refund?',
        reply:
            'Your refund is at "Refund Initiated": the money is on the way, but it has not been credited to your bank yet. ' +
            'It will show as "Bank Credited" once it arrives.\n\n' +
            '(Demo mode: this is a simulated status, not a real refund.)',
        events: [
            { type: 'thinking', text: 'Customer asks about refund status. I need the current return status.' },
            { type: 'tool', text: '[Simulated] get-return-status for the demo return.' },
            { type: 'store', text: '[Simulated] REFUND_INITIATED (not REFUND_CREDITED).' },
            { type: 'thinking', text: 'Refund is initiated, not credited. I must not say the money has arrived.' },
        ],
        timelineStep: 4,
        opensApproval: false,
    },
];