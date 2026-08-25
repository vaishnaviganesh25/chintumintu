import { useMemo, useState } from 'react';
import type { TransactionInput, ValidationErrors } from '../types';
import {
  validateVPA,
  validateAmount,
  validateVpaAge,
  validateTimestamp,
  validateGapSeconds,
} from '../utils/validation';
import {
  buildScenarios,
  toTransactionInput,
  EMPTY_FORM,
  type FormValues,
  type Scenario,
} from '../utils/scenarios';

interface TransactionSimulatorProps {
  onSimulate: (data: TransactionInput) => Promise<void>;
  isLoading: boolean;
}

const FIELD_CLASS =
  'w-full px-3 py-2 bg-[var(--sunk)] border border-[var(--rule-strong)] rounded-md text-[var(--ink)] ' +
  ' focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:border-[var(--accent)] ' +
  'disabled:opacity-60';

const LABEL_CLASS = 'block text-sm font-medium text-[var(--ink)] mb-2';

export function TransactionSimulator({ onSimulate, isLoading }: TransactionSimulatorProps) {
  const [formData, setFormData] = useState<FormValues>(EMPTY_FORM);
  const [errors, setErrors] = useState<ValidationErrors>({});
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [runningStep, setRunningStep] = useState<string | null>(null);

  // Presets are built once per mount: each one stamps today's date at a fixed hour,
  // so rebuilding them on every render would churn the timestamps for no reason.
  const scenarios = useMemo(() => buildScenarios(), []);

  const validateForm = (values: FormValues) => {
    const next: ValidationErrors = {};

    if (!validateVPA(values.senderVPA)) {
      next.senderVPA = 'Sender VPA must look like name@handle (e.g. user@ybl)';
    }
    if (!validateVPA(values.receiverVPA)) {
      next.receiverVPA = 'Receiver VPA must look like name@handle (e.g. merchant@paytm)';
    }
    if (!validateAmount(values.amount)) {
      next.amount = 'Amount must be a positive number';
    }
    if (!validateVpaAge(values.receiverVpaAgeDays)) {
      next.receiverVpaAgeDays = 'Enter a whole number of days between 0 and 1000';
    }
    if (!validateTimestamp(values.timestamp)) {
      next.timestamp = 'Enter a valid date and time, or leave blank to use the server clock';
    }
    if (!validateGapSeconds(values.timeSinceLastTxnSec)) {
      next.timeSinceLastTxnSec = 'Enter seconds as a number, or -1 for no prior activity';
    }

    setErrors(next);
    return Object.keys(next).length === 0;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isLoading || !validateForm(formData)) return;
    await onSimulate(toTransactionInput(formData));
  };

  /**
   * Fill the form from a preset and fire its legs in order.
   *
   * Sequential awaits matter for the Rs.1 test: the second leg is only interesting
   * because the API has already recorded the first, and the backward-looking features
   * read that history. Firing both at once would race, and the drain would be scored
   * as though the probe had never happened.
   */
  const runScenario = async (scenario: Scenario) => {
    if (isLoading) return;
    setErrors({});

    for (const step of scenario.steps) {
      setFormData(step.values);
      setRunningStep(step.caption ?? null);
      await onSimulate(toTransactionInput(step.values));
    }
    setRunningStep(null);
  };

  const update = (field: keyof FormValues, value: string) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
    if (errors[field as keyof ValidationErrors]) {
      setErrors((prev) => ({ ...prev, [field]: undefined }));
    }
  };

  const isFormValid =
    validateVPA(formData.senderVPA) &&
    validateVPA(formData.receiverVPA) &&
    validateAmount(formData.amount) &&
    validateVpaAge(formData.receiverVpaAgeDays) &&
    validateTimestamp(formData.timestamp) &&
    validateGapSeconds(formData.timeSinceLastTxnSec);

  const fieldError = (key: keyof ValidationErrors, id: string) =>
    errors[key] ? (
      <span id={`${id}-error`} className="text-[var(--hold)] text-sm mt-1 block" role="alert">
        {errors[key]}
      </span>
    ) : null;

  return (
    <div className="fg-surface p-5">
      <h2 className="text-[13px] font-semibold mb-1">Transaction Simulator</h2>
      <p className="text-sm text-[var(--muted)] mb-5">
        Score a payment against the live model, or replay one of the scam signatures it
        was trained to catch.
      </p>

      {/* Scenario presets ------------------------------------------------ */}
      <fieldset className="mb-6" disabled={isLoading}>
        <legend className="text-xs uppercase tracking-wider text-[var(--faint)] mb-2">
          Replay a signature
        </legend>
        <div className="flex flex-wrap gap-2">
          {scenarios.map((scenario) => (
            <button
              key={scenario.id}
              type="button"
              onClick={() => void runScenario(scenario)}
              disabled={isLoading}
              title={scenario.blurb}
              className={
                'px-3 py-1.5 rounded-md text-sm border transition-colors duration-150 ' +
                'focus:outline-none focus:ring-2 focus:ring-[var(--accent)] disabled:opacity-50 ' +
                'disabled:cursor-not-allowed ' +
                (scenario.hostile
                  ? 'border-[var(--hold)] text-[var(--hold)] hover:bg-[var(--hold-soft)]'
                  : 'border-[var(--rule-strong)] bg-[var(--sunk)] text-[var(--ink)] hover:bg-[var(--sunk)]')
              }
            >
              {scenario.label}
            </button>
          ))}
        </div>
        {runningStep && (
          <p className="text-xs text-[var(--accent)] mt-2" aria-live="polite">
            Running {runningStep}
          </p>
        )}
      </fieldset>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className={LABEL_CLASS} htmlFor="senderVPA">Sender VPA</label>
          <input
            id="senderVPA"
            type="text"
            value={formData.senderVPA}
            onChange={(e) => update('senderVPA', e.target.value)}
            placeholder="user@ybl"
            className={FIELD_CLASS}
            disabled={isLoading}
            aria-describedby={errors.senderVPA ? 'senderVPA-error' : undefined}
          />
          {fieldError('senderVPA', 'senderVPA')}
        </div>

        <div>
          <label className={LABEL_CLASS} htmlFor="receiverVPA">Receiver VPA</label>
          <input
            id="receiverVPA"
            type="text"
            value={formData.receiverVPA}
            onChange={(e) => update('receiverVPA', e.target.value)}
            placeholder="merchant@paytm"
            className={FIELD_CLASS}
            disabled={isLoading}
            aria-describedby={errors.receiverVPA ? 'receiverVPA-error' : undefined}
          />
          {fieldError('receiverVPA', 'receiverVPA')}
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className={LABEL_CLASS} htmlFor="amount">Amount (INR)</label>
            <input
              id="amount"
              type="number"
              value={formData.amount}
              onChange={(e) => update('amount', e.target.value)}
              placeholder="500"
              min="0"
              step="0.01"
              className={FIELD_CLASS}
              disabled={isLoading}
              aria-describedby={errors.amount ? 'amount-error' : undefined}
            />
            {fieldError('amount', 'amount')}
          </div>

          <div>
            <label className={LABEL_CLASS} htmlFor="receiverVpaAgeDays">
              Receiver VPA age (days)
              <span className="text-[var(--faint)] font-normal"> &mdash; optional</span>
            </label>
            <input
              id="receiverVpaAgeDays"
              type="number"
              value={formData.receiverVpaAgeDays}
              onChange={(e) => update('receiverVpaAgeDays', e.target.value)}
              placeholder="0 for a brand-new account"
              min="0"
              max="1000"
              step="1"
              className={FIELD_CLASS}
              disabled={isLoading}
              aria-describedby={
                errors.receiverVpaAgeDays ? 'receiverVpaAgeDays-error' : 'receiverVpaAgeDays-help'
              }
            />
            {errors.receiverVpaAgeDays ? (
              fieldError('receiverVpaAgeDays', 'receiverVpaAgeDays')
            ) : (
              <span id="receiverVpaAgeDays-help" className="text-[var(--faint)] text-xs mt-1 block">
                The strongest single signal in the model. Left blank, the engine assumes an
                established account and approves almost anything.
              </span>
            )}
          </div>
        </div>

        <div>
          <label className={LABEL_CLASS} htmlFor="timestamp">
            Transaction time
            <span className="text-[var(--faint)] font-normal"> &mdash; optional</span>
          </label>
          <input
            id="timestamp"
            type="datetime-local"
            value={formData.timestamp}
            onChange={(e) => update('timestamp', e.target.value)}
            className={FIELD_CLASS}
            disabled={isLoading}
            aria-describedby={errors.timestamp ? 'timestamp-error' : 'timestamp-help'}
          />
          {errors.timestamp ? (
            fieldError('timestamp', 'timestamp')
          ) : (
            <span id="timestamp-help" className="text-[var(--faint)] text-xs mt-1 block">
              Set an hour between 01:00 and 04:00 to reach the odd-hour phishing signature.
              Blank uses the server clock.
            </span>
          )}
        </div>

        <div>
          <button
            type="button"
            onClick={() => setShowAdvanced((v) => !v)}
            className="text-xs text-[var(--muted)] hover:text-[var(--accent)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)] rounded px-1 py-0.5"
            aria-expanded={showAdvanced}
            aria-controls="advanced-fields"
          >
            {showAdvanced ? 'Hide' : 'Show'} sender context
          </button>

          {showAdvanced && (
            <div id="advanced-fields" className="grid grid-cols-1 sm:grid-cols-2 gap-4 mt-3">
              <div>
                <label className={LABEL_CLASS} htmlFor="senderCity">Sender city</label>
                <input
                  id="senderCity"
                  type="text"
                  value={formData.senderCity}
                  onChange={(e) => update('senderCity', e.target.value)}
                  placeholder="Mumbai"
                  maxLength={64}
                  className={FIELD_CLASS}
                  disabled={isLoading}
                />
              </div>

              <div>
                <label className={LABEL_CLASS} htmlFor="timeSinceLastTxnSec">
                  Seconds since last payment
                </label>
                <input
                  id="timeSinceLastTxnSec"
                  type="number"
                  value={formData.timeSinceLastTxnSec}
                  onChange={(e) => update('timeSinceLastTxnSec', e.target.value)}
                  placeholder="-1 if none"
                  step="1"
                  className={FIELD_CLASS}
                  disabled={isLoading}
                  aria-describedby={
                    errors.timeSinceLastTxnSec ? 'timeSinceLastTxnSec-error' : 'gap-help'
                  }
                />
                {errors.timeSinceLastTxnSec ? (
                  fieldError('timeSinceLastTxnSec', 'timeSinceLastTxnSec')
                ) : (
                  <span id="gap-help" className="text-[var(--faint)] text-xs mt-1 block">
                    Overrides the server-side history lookup.
                  </span>
                )}
              </div>
            </div>
          )}
        </div>

        <button
          type="submit"
          disabled={!isFormValid || isLoading}
          className="w-full bg-[var(--accent)] hover:bg-[var(--accent-hover)] disabled:opacity-50 disabled:cursor-not-allowed text-[var(--ink)] font-medium py-2 px-4 rounded-md transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:ring-offset-2"
          title={!isFormValid ? 'Fill sender, receiver and amount to continue' : undefined}
        >
          {isLoading ? (
            <span className="flex items-center justify-center">
              <svg className="animate-spin -ml-1 mr-3 h-5 w-5 text-[var(--ink)]" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
              </svg>
              Scoring...
            </span>
          ) : (
            'Score transaction'
          )}
        </button>
      </form>
    </div>
  );
}
