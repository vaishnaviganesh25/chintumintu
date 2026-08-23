import type { TransactionInput, ValidationErrors } from '../types';

/**
 * Validates VPA format (must contain "@" symbol)
 */
export function validateVPA(vpa: string): boolean {
  return vpa.trim().length > 0 && vpa.includes('@');
}

/**
 * Validates amount (must be positive number)
 */
export function validateAmount(amount: string): boolean {
  const trimmed = amount.trim();
  if (trimmed === '') return false;
  
  const num = Number(trimmed);
  // Check if it's a valid number and positive
  // Number() is stricter than parseFloat() - it rejects "10abc"
  return !isNaN(num) && num > 0 && isFinite(num);
}

/**
 * Validates the optional receiver VPA age.
 *
 * Blank is valid - the field is optional and the backend applies its own default.
 * Anything present must be a whole number of days inside the range the model was
 * trained on, matching the API's own 0-1000 bound so the error surfaces here rather
 * than as a 422 round trip.
 */
export function validateVpaAge(age: string): boolean {
  const trimmed = age.trim();
  if (trimmed === '') return true;

  const num = Number(trimmed);
  return Number.isInteger(num) && num >= 0 && num <= 1000;
}

/**
 * Validates the optional transaction timestamp.
 *
 * Blank is valid - the API falls back to its own clock. Anything present must parse
 * as a real local datetime. The value comes from `<input type="datetime-local">`,
 * which already constrains the shape, but a user can still paste rubbish into it in
 * some browsers and an unparseable string would reach the API as a 422.
 */
const LOCAL_DATETIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$/;

export function validateTimestamp(timestamp: string): boolean {
  const trimmed = timestamp.trim();
  if (trimmed === '') return true;

  // The shape is checked before the parse because `Date` is lenient in ways that
  // silently change the value: `new Date("2026-08-")` does not fail, it returns
  // 1 August 2026. A truncated string would sail through a parse-only check and
  // reach the model as a different transaction than the one on screen.
  if (!LOCAL_DATETIME.test(trimmed)) return false;

  const parsed = new Date(trimmed);
  if (Number.isNaN(parsed.getTime())) return false;

  // Reject values that parse but roll over - "2026-02-31" becomes 3 March. Comparing
  // the parsed month back against the input catches every such overflow.
  const [datePart] = trimmed.split('T');
  const [year, month, day] = datePart.split('-').map(Number);
  return (
    parsed.getFullYear() === year &&
    parsed.getMonth() + 1 === month &&
    parsed.getDate() === day
  );
}

/**
 * Validates the optional gap since the sender's previous payment.
 *
 * Blank is valid - the API derives it from its own history store. Present values
 * must be a finite number of seconds, and -1 is the documented encoding for "no
 * prior activity", so the floor is -1 rather than 0.
 */
export function validateGapSeconds(gap: string): boolean {
  const trimmed = gap.trim();
  if (trimmed === '') return true;

  const num = Number(trimmed);
  return Number.isFinite(num) && num >= -1;
}

/**
 * Validates complete transaction input
 */
export function validateTransactionInput(
  input: Partial<TransactionInput> & { amount: number | string }
): ValidationErrors {
  const errors: ValidationErrors = {};

  if (input.senderVPA !== undefined && !validateVPA(input.senderVPA)) {
    errors.senderVPA = 'Sender VPA must contain @ symbol (e.g., user@ybl)';
  }

  if (input.receiverVPA !== undefined && !validateVPA(input.receiverVPA)) {
    errors.receiverVPA =
      'Receiver VPA must contain @ symbol (e.g., merchant@paytm)';
  }

  if (
    input.amount !== undefined &&
    !validateAmount(input.amount.toString())
  ) {
    errors.amount = 'Amount must be a positive number';
  }

  return errors;
}
