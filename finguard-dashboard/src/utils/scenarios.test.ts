import { describe, expect, it } from 'vitest';
import fc from 'fast-check';
import {
  buildScenarios,
  toLocalInputValue,
  toTransactionInput,
  EMPTY_FORM,
  type FormValues,
} from './scenarios';

/**
 * The scenarios are the demo. If a preset stops producing the transaction it claims
 * to, the failure is silent - the payment still scores, just not as the signature it
 * is labelled with - so these assert the properties each preset exists to express.
 */
describe('scenario presets', () => {
  const scenarios = buildScenarios();

  it('offers a legitimate control alongside the hostile cases', () => {
    expect(scenarios.some((s) => !s.hostile)).toBe(true);
    expect(scenarios.filter((s) => s.hostile).length).toBeGreaterThanOrEqual(3);
  });

  it('gives every preset a stable id and human-readable copy', () => {
    const ids = scenarios.map((s) => s.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const s of scenarios) {
      expect(s.label.length).toBeGreaterThan(0);
      expect(s.blurb.length).toBeGreaterThan(0);
      expect(s.steps.length).toBeGreaterThan(0);
    }
  });

  it('puts the odd-hour preset inside the 01:00-04:00 window', () => {
    // The window the model keys on is 01:00:00 to 03:59:59. A preset that drifts to
    // 04:00 would demo the wrong thing while still looking plausible.
    const oddHour = scenarios.find((s) => s.id === 'odd-hour');
    expect(oddHour).toBeDefined();

    const hour = new Date(oddHour!.steps[0].values.timestamp).getHours();
    expect(hour).toBeGreaterThanOrEqual(1);
    expect(hour).toBeLessThan(4);
  });

  it('makes the mule preset a brand-new receiver with a large amount', () => {
    const mule = scenarios.find((s) => s.id === 'mule')!.steps[0].values;
    expect(Number(mule.receiverVpaAgeDays)).toBe(0);
    expect(Number(mule.amount)).toBeGreaterThanOrEqual(15_000);
  });

  it('builds the Rs.1 test as two legs to one receiver, seconds apart', () => {
    // The scam is a *pair*. A single-step version of this preset would demo a large
    // payment to a new account, which is a different signature entirely.
    const legs = scenarios.find((s) => s.id === 'rupee-one')!.steps;
    expect(legs).toHaveLength(2);

    const [probe, drain] = legs.map((l) => l.values);
    expect(Number(probe.amount)).toBe(1);
    expect(Number(drain.amount)).toBeGreaterThan(10_000);
    expect(drain.receiverVPA).toBe(probe.receiverVPA);
    expect(drain.senderVPA).toBe(probe.senderVPA);
    expect(Number(drain.timeSinceLastTxnSec)).toBeLessThanOrEqual(60);
    expect(legs.every((l) => l.caption)).toBe(true);
  });

  it('supplies every field the API accepts, so no preset relies on a server default', () => {
    for (const scenario of scenarios) {
      for (const step of scenario.steps) {
        for (const key of Object.keys(EMPTY_FORM) as (keyof FormValues)[]) {
          expect(step.values[key].trim()).not.toBe('');
        }
      }
    }
  });
});

describe('toLocalInputValue', () => {
  it('renders naive local time, never a UTC instant', () => {
    // toISOString() would shift the hour by the local offset, which is exactly the
    // bug that made the odd-hour signature unreachable in the first place.
    const d = new Date(2026, 7, 23, 3, 12);
    expect(toLocalInputValue(d)).toBe('2026-08-23T03:12');
  });

  it('round-trips any local datetime back to the same wall-clock reading', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 2020, max: 2035 }),
        fc.integer({ min: 0, max: 11 }),
        fc.integer({ min: 1, max: 28 }),
        fc.integer({ min: 0, max: 23 }),
        fc.integer({ min: 0, max: 59 }),
        (year, month, day, hour, minute) => {
          const original = new Date(year, month, day, hour, minute);
          const parsed = new Date(toLocalInputValue(original));

          expect(parsed.getFullYear()).toBe(year);
          expect(parsed.getMonth()).toBe(month);
          expect(parsed.getDate()).toBe(day);
          expect(parsed.getHours()).toBe(hour);
          expect(parsed.getMinutes()).toBe(minute);
        },
      ),
      { numRuns: 200 },
    );
  });

  it('zero-pads every component to a fixed width', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 0, max: 9 }),
        fc.integer({ min: 1, max: 9 }),
        (hour, day) => {
          const value = toLocalInputValue(new Date(2026, 0, day, hour, 5));
          expect(value).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/);
        },
      ),
      { numRuns: 100 },
    );
  });
});

describe('toTransactionInput', () => {
  const filled: FormValues = {
    senderVPA: '  rahul.verma@okicici  ',
    receiverVPA: 'raju.kirana@okbizaxis',
    amount: '240',
    receiverVpaAgeDays: '412',
    timestamp: '2026-08-23T13:24',
    senderCity: ' Pune ',
    timeSinceLastTxnSec: '3600',
  };

  it('trims strings and coerces the numeric fields', () => {
    const input = toTransactionInput(filled);

    expect(input.senderVPA).toBe('rahul.verma@okicici');
    expect(input.senderCity).toBe('Pune');
    expect(input.amount).toBe(240);
    expect(input.receiverVpaAgeDays).toBe(412);
    expect(input.timeSinceLastTxnSec).toBe(3600);
  });

  it('omits blank optional fields rather than sending them as empty or null', () => {
    // The API applies a documented default per field. Sending "" or null would either
    // 422 or override that default with a meaningless value.
    const sparse: FormValues = {
      ...EMPTY_FORM,
      senderVPA: 'a.b@ybl',
      receiverVPA: 'shop@paytm',
      amount: '100',
    };
    const input = toTransactionInput(sparse);

    expect(input).not.toHaveProperty('receiverVpaAgeDays');
    expect(input).not.toHaveProperty('timestamp');
    expect(input).not.toHaveProperty('senderCity');
    expect(input).not.toHaveProperty('timeSinceLastTxnSec');
  });

  it('never emits NaN for a field it chose to include', () => {
    fc.assert(
      fc.property(
        fc.float({ min: Math.fround(0.01), max: 1_000_000, noNaN: true }),
        fc.integer({ min: 0, max: 1000 }),
        fc.integer({ min: -1, max: 86_400 }),
        (amount, age, gap) => {
          const input = toTransactionInput({
            ...filled,
            amount: String(amount),
            receiverVpaAgeDays: String(age),
            timeSinceLastTxnSec: String(gap),
          });

          expect(Number.isNaN(input.amount)).toBe(false);
          expect(Number.isNaN(input.receiverVpaAgeDays!)).toBe(false);
          expect(Number.isNaN(input.timeSinceLastTxnSec!)).toBe(false);
        },
      ),
      { numRuns: 200 },
    );
  });

  it('keeps the age field as a whole number of days', () => {
    fc.assert(
      fc.property(fc.integer({ min: 0, max: 1000 }), (age) => {
        const input = toTransactionInput({ ...filled, receiverVpaAgeDays: `${age}` });
        expect(Number.isInteger(input.receiverVpaAgeDays!)).toBe(true);
      }),
      { numRuns: 100 },
    );
  });

  it('produces a payload the API would accept from every shipped preset', () => {
    for (const scenario of buildScenarios()) {
      for (const step of scenario.steps) {
        const input = toTransactionInput(step.values);

        expect(input.senderVPA).toContain('@');
        expect(input.receiverVPA).toContain('@');
        expect(input.amount).toBeGreaterThan(0);
        expect(input.receiverVpaAgeDays).toBeGreaterThanOrEqual(0);
        expect(input.receiverVpaAgeDays).toBeLessThanOrEqual(1000);
        expect(input.timeSinceLastTxnSec).toBeGreaterThanOrEqual(-1);
      }
    }
  });
});
