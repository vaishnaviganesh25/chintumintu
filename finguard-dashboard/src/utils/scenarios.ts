import type { TransactionInput } from '../types';

/**
 * Canned transactions, one per fraud signature the model was trained to catch.
 *
 * These exist because two of the three signatures are unreachable by hand. Odd-hour
 * phishing keys on 01:00-04:00, so typing a plausible transaction during a daytime
 * demo can never produce it; and the Rs.1 test is defined by a *pair* of payments
 * seconds apart to the same receiver, which no single form submission can express.
 * A reviewer who has to fake the system clock or fire two curl calls by hand to see
 * the headline behaviour will simply not see it.
 */

export interface ScenarioStep {
  /** Shown while this leg is in flight, e.g. "leg 1 of 2 - the Rs.1 probe". */
  caption?: string;
  values: FormValues;
}

export interface Scenario {
  id: string;
  label: string;
  blurb: string;
  /** Fraudulent scenarios get a warning tint; the control case does not. */
  hostile: boolean;
  steps: ScenarioStep[];
}

export interface FormValues {
  senderVPA: string;
  receiverVPA: string;
  amount: string;
  receiverVpaAgeDays: string;
  timestamp: string;
  senderCity: string;
  timeSinceLastTxnSec: string;
}

export const EMPTY_FORM: FormValues = {
  senderVPA: '',
  receiverVPA: '',
  amount: '',
  receiverVpaAgeDays: '',
  timestamp: '',
  senderCity: '',
  timeSinceLastTxnSec: '',
};

/**
 * Format a Date for an `<input type="datetime-local">`, which wants naive local
 * time — no timezone suffix, no seconds. Building it from the local getters rather
 * than `toISOString()` is deliberate: `toISOString` converts to UTC, which would
 * shift an intentional 03:12 into some other hour and defeat the whole point.
 */
export function toLocalInputValue(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}`
  );
}

/** Today's date at a fixed wall-clock time, so a preset reads the same every run. */
function todayAt(hour: number, minute: number): string {
  const d = new Date();
  d.setHours(hour, minute, 0, 0);
  return toLocalInputValue(d);
}

export function buildScenarios(): Scenario[] {
  return [
    {
      id: 'everyday',
      label: 'Everyday payment',
      blurb: 'Rs.240 to a kirana store at lunchtime, from an established account.',
      hostile: false,
      steps: [
        {
          values: {
            senderVPA: 'rahul.verma@okicici',
            receiverVPA: 'raju.kirana@okbizaxis',
            amount: '240',
            receiverVpaAgeDays: '412',
            timestamp: todayAt(13, 24),
            senderCity: 'Pune',
            timeSinceLastTxnSec: '18400',
          },
        },
      ],
    },
    {
      id: 'odd-hour',
      label: 'Odd-hour phishing',
      blurb: 'Rs.25,400 at 03:12 to a VPA opened two days ago — a screen-share scam draining an account overnight.',
      hostile: true,
      steps: [
        {
          values: {
            senderVPA: '8266605706@ibl',
            receiverVPA: 'girindra.bhat@ybl',
            amount: '25400',
            receiverVpaAgeDays: '2',
            timestamp: todayAt(3, 12),
            senderCity: 'Mumbai',
            timeSinceLastTxnSec: '5200',
          },
        },
      ],
    },
    {
      id: 'mule',
      label: 'New-VPA mule',
      blurb: 'Rs.48,500 into an account created today — the collection leg of a mule ring.',
      hostile: true,
      steps: [
        {
          values: {
            senderVPA: '9876543210@ybl',
            receiverVPA: 'quickcash.help@paytm',
            amount: '48500',
            receiverVpaAgeDays: '0',
            timestamp: todayAt(21, 47),
            senderCity: 'Bengaluru',
            timeSinceLastTxnSec: '95',
          },
        },
      ],
    },
    {
      id: 'rupee-one',
      label: 'Rs.1 test (2 legs)',
      blurb: 'A Rs.1 "account check", then Rs.62,000 to the same receiver 43 seconds later. Watch leg 1 clear and leg 2 get held for the sequence, not the size.',
      hostile: true,
      steps: [
        {
          caption: 'leg 1 of 2 — the Rs.1 probe',
          values: {
            senderVPA: 'victim.suresh@okhdfcbank',
            receiverVPA: 'verify.acct@paytm',
            amount: '1',
            receiverVpaAgeDays: '0',
            timestamp: todayAt(20, 15),
            senderCity: 'Chennai',
            timeSinceLastTxnSec: '7200',
          },
        },
        {
          caption: 'leg 2 of 2 — the drain, 43s later',
          values: {
            senderVPA: 'victim.suresh@okhdfcbank',
            receiverVPA: 'verify.acct@paytm',
            amount: '62000',
            receiverVpaAgeDays: '0',
            timestamp: todayAt(20, 15),
            senderCity: 'Chennai',
            timeSinceLastTxnSec: '43',
          },
        },
      ],
    },
  ];
}

/** Form strings -> the API client's input shape, dropping anything left blank. */
export function toTransactionInput(values: FormValues): TransactionInput {
  const age = values.receiverVpaAgeDays.trim();
  const gap = values.timeSinceLastTxnSec.trim();
  const city = values.senderCity.trim();
  const ts = values.timestamp.trim();

  return {
    senderVPA: values.senderVPA.trim(),
    receiverVPA: values.receiverVPA.trim(),
    amount: parseFloat(values.amount),
    ...(age === '' ? {} : { receiverVpaAgeDays: parseInt(age, 10) }),
    ...(gap === '' ? {} : { timeSinceLastTxnSec: parseFloat(gap) }),
    ...(city === '' ? {} : { senderCity: city }),
    ...(ts === '' ? {} : { timestamp: ts }),
  };
}
