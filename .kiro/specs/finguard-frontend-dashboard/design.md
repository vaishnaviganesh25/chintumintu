# Technical Design Document: FinGuard Frontend Dashboard

## Overview

The FinGuard Frontend Dashboard is a modern, responsive React-based web application that provides an interactive interface for simulating and visualizing UPI fraud detection. The application demonstrates real-time fraud analysis capabilities through a mock service layer while the actual Spring Boot backend is under development.

### Key Design Principles

1. **Component-Based Architecture**: Modular React components with clear separation of concerns
2. **Mock-First Development**: Hardcoded mock service enables frontend development independent of backend
3. **Explainability-First**: XAI visualizations are first-class citizens, not afterthoughts
4. **Accessibility by Default**: WCAG 2.1 AA compliance throughout the interface
5. **Responsive Design**: Mobile-first approach with progressive enhancement for larger screens

### Technology Choices

- **React 18.x + Vite**: Fast development experience with HMR, modern JSX transform
- **Tailwind CSS 3.x**: Utility-first CSS for rapid UI development and consistent design tokens
- **Recharts 2.x**: Declarative charting library with excellent React integration for SHAP visualizations
- **React Hook Form**: Performant form validation with minimal re-renders
- **Framer Motion**: Smooth animations for gauge, transitions, and loading states

## Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     FinGuard Dashboard (SPA)                  │
│                                                               │
│  ┌─────────────────┐  ┌──────────────────┐  ┌─────────────┐ │
│  │   Presentation  │  │   State Logic    │  │   Service   │ │
│  │     Layer       │  │      Layer       │  │    Layer    │ │
│  │                 │  │                  │  │             │ │
│  │  - Components   │◄─┤  - React State   │◄─┤  - Mock API │ │
│  │  - Layouts      │  │  - Form State    │  │  - Utils    │ │
│  │  - Styles       │  │  - Validation    │  │             │ │
│  └─────────────────┘  └──────────────────┘  └─────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### Component Hierarchy

```
App
├── Header
├── DashboardLayout
│   ├── TransactionSimulator
│   │   ├── InputField (Sender VPA)
│   │   ├── InputField (Receiver VPA)
│   │   ├── InputField (Amount)
│   │   └── SimulateButton
│   ├── EvaluationPanel
│   │   ├── LoadingSpinner
│   │   ├── StatusBadge
│   │   ├── RiskGauge
│   │   └── LatencyMetric
│   └── XAIPanel
│       ├── ExplanationText
│       └── SHAPChart
```

### Data Flow

1. **User Input**: User enters transaction details in TransactionSimulator form
2. **Validation**: React Hook Form validates inputs (VPA format, positive amount)
3. **Submission**: Form submission triggers Mock Service API call
4. **Loading State**: EvaluationPanel displays loading spinner during 50ms simulated delay
5. **Mock Response**: Mock Service returns hardcoded fraud detection result
6. **State Update**: React state updated with fraud detection response
7. **UI Update**: EvaluationPanel and XAIPanel render results with animations

### State Management Strategy

**Local Component State** (using useState):
- Form input values (Sender VPA, Receiver VPA, Amount)
- Loading state (isLoading boolean)
- Validation errors (per-field error messages)
- Fraud detection results (response object)

**Why Local State Instead of Context/Redux**:
- Single-page application with minimal state sharing
- No deeply nested components requiring prop drilling
- Form state naturally belongs to TransactionSimulator
- Results state naturally belongs to parent DashboardLayout

## Components and Interfaces

### Core Components

#### 1. Header Component

**Purpose**: Display application branding and title

**Props**: None

**State**: None

**Rendering**:
```jsx
<header className="bg-gray-900 border-b border-cyan-500 py-6 px-8">
  <h1 className="text-4xl font-bold text-cyan-400">FinGuard</h1>
  <p className="text-gray-400 text-sm">Real-Time UPI Fraud Detection Engine</p>
</header>
```

---

#### 2. TransactionSimulator Component

**Purpose**: Input form for transaction details with validation

**Props**: 
- `onSimulate: (data: TransactionInput) => Promise<void>` - Callback when form submitted
- `isLoading: boolean` - Disable form during API call

**State**:
- `senderVPA: string`
- `receiverVPA: string`
- `amount: string`
- `errors: Record<string, string>`

**Validation Rules**:
- Sender VPA: Must contain "@" symbol, non-empty
- Receiver VPA: Must contain "@" symbol, non-empty
- Amount: Must be positive number, non-empty

**Methods**:
- `handleSubmit()`: Validates and calls onSimulate prop
- `validateVPA(vpa: string): boolean`: Returns true if VPA contains "@"
- `validateAmount(amount: string): boolean`: Returns true if positive number

---

#### 3. EvaluationPanel Component

**Purpose**: Display fraud detection results or loading state

**Props**:
- `isLoading: boolean`
- `results: FraudDetectionResponse | null`

**Rendering Logic**:
- If `isLoading === true`: Display LoadingSpinner
- If `results === null && !isLoading`: Display placeholder text
- If `results !== null && !isLoading`: Display StatusBadge, RiskGauge, LatencyMetric

**Sub-components**:
- **StatusBadge**: Shows "TRANSACTION BLOCKED" (red) or "APPROVED" (green)
- **RiskGauge**: Radial progress indicator with color-coded risk levels
- **LatencyMetric**: Small badge showing "Inference Time: Xms"

---

#### 4. RiskGauge Component

**Purpose**: Visualize fraud probability as animated gauge

**Props**:
- `probability: number` (0.0 to 1.0)

**Color Logic**:
- `probability > 0.70`: Red (`text-red-500`)
- `0.40 <= probability <= 0.70`: Yellow (`text-yellow-500`)
- `probability < 0.40`: Green (`text-green-500`)

**Animation**: Framer Motion animates from 0 to target percentage over 1 second

**Implementation**:
```jsx
<motion.div
  initial={{ scale: 0 }}
  animate={{ scale: 1 }}
  transition={{ duration: 0.5 }}
>
  <CircularProgressbar
    value={probability * 100}
    text={`${(probability * 100).toFixed(0)}%`}
    styles={buildStyles({
      pathColor: getColorForProbability(probability),
      textColor: '#fff',
    })}
  />
</motion.div>
```

---

#### 5. XAIPanel Component

**Purpose**: Display explainable AI information (text explanation and SHAP chart)

**Props**:
- `explanation: string | null`
- `shapFeatures: SHAPFeature[] | null`

**Rendering Logic**:
- If `explanation === null`: Display placeholder "No data available"
- If `explanation !== null`: Display ExplanationText and SHAPChart

**Layout**: Two-column layout on desktop, stacked on mobile

---

#### 6. SHAPChart Component

**Purpose**: Horizontal bar chart showing feature importance

**Props**:
- `features: SHAPFeature[]` where `SHAPFeature = { feature: string, importance: number }`

**Data Processing**:
1. Sort features by importance descending
2. Convert importance to percentage (multiply by 100)
3. Apply color gradient based on magnitude

**Implementation** (using Recharts):
```jsx
<ResponsiveContainer width="100%" height={300}>
  <BarChart data={sortedFeatures} layout="vertical">
    <XAxis type="number" domain={[0, 100]} />
    <YAxis type="category" dataKey="feature" width={150} />
    <Tooltip formatter={(value) => `${value}%`} />
    <Bar dataKey="importance" fill="#06b6d4" />
  </BarChart>
</ResponsiveContainer>
```

---

#### 7. LoadingSpinner Component

**Purpose**: Indicate processing state during simulation

**Props**: None

**Implementation**:
```jsx
<div className="flex justify-center items-center h-64">
  <div className="animate-spin rounded-full h-16 w-16 border-t-4 border-cyan-500"></div>
</div>
```

---

### Service Layer

#### MockFraudService

**Purpose**: Simulate backend API calls with hardcoded responses

**Methods**:

```typescript
export async function simulateFraudDetection(
  input: TransactionInput
): Promise<FraudDetectionResponse> {
  // Simulate network latency
  await new Promise(resolve => setTimeout(resolve, 50));
  
  // Return hardcoded response
  return {
    transaction_id: "tx-987654321",
    status: "BLOCKED",
    fraud_probability: 0.92,
    execution_time_ms: 42,
    xai_explanation: "Transaction blocked due to unusually high velocity of transfers to a newly created VPA combined with an anomalous time-of-day.",
    shap_features: [
      { feature: "Receiver VPA Age", importance: 0.45 },
      { feature: "Time Since Last Txn", importance: 0.30 },
      { feature: "Transaction Amount", importance: 0.17 },
      { feature: "Location Delta", importance: 0.08 }
    ]
  };
}
```

**Future Enhancement**: Replace hardcoded response with actual API call to Spring Boot backend

---

## Data Models

### TypeScript Interfaces

```typescript
/**
 * User input for transaction simulation
 */
export interface TransactionInput {
  senderVPA: string;      // Format: user@provider (e.g., john@ybl)
  receiverVPA: string;    // Format: user@provider (e.g., merchant@paytm)
  amount: number;         // Transaction amount in INR
}

/**
 * Mock fraud detection response
 */
export interface FraudDetectionResponse {
  transaction_id: string;           // Unique transaction identifier
  status: "BLOCKED" | "APPROVED";   // Fraud decision
  fraud_probability: number;        // Risk score (0.0 to 1.0)
  execution_time_ms: number;        // Inference latency in milliseconds
  xai_explanation: string;          // Human-readable explanation
  shap_features: SHAPFeature[];     // Feature importance breakdown
}

/**
 * SHAP feature importance data point
 */
export interface SHAPFeature {
  feature: string;        // Feature name (e.g., "Receiver VPA Age")
  importance: number;     // Importance value (0.0 to 1.0)
}

/**
 * Form validation error state
 */
export interface ValidationErrors {
  senderVPA?: string;
  receiverVPA?: string;
  amount?: string;
}

/**
 * Application state (managed in DashboardLayout)
 */
export interface DashboardState {
  isLoading: boolean;
  results: FraudDetectionResponse | null;
  error: string | null;
}
```

### Validation Logic

```typescript
/**
 * Validates VPA format (must contain "@" symbol)
 */
export function validateVPA(vpa: string): boolean {
  return vpa.trim().length > 0 && vpa.includes("@");
}

/**
 * Validates amount (must be positive number)
 */
export function validateAmount(amount: string): boolean {
  const num = parseFloat(amount);
  return !isNaN(num) && num > 0;
}

/**
 * Validates complete transaction input
 */
export function validateTransactionInput(
  input: TransactionInput
): ValidationErrors {
  const errors: ValidationErrors = {};
  
  if (!validateVPA(input.senderVPA)) {
    errors.senderVPA = "Sender VPA must contain @ symbol (e.g., user@ybl)";
  }
  
  if (!validateVPA(input.receiverVPA)) {
    errors.receiverVPA = "Receiver VPA must contain @ symbol (e.g., merchant@paytm)";
  }
  
  if (!validateAmount(input.amount.toString())) {
    errors.amount = "Amount must be a positive number";
  }
  
  return errors;
}
```


## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system—essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Submit Button Enabled State

*For any* combination of form field values (Sender VPA, Receiver VPA, Amount), the "Simulate Transaction" button SHALL be enabled if and only if all fields contain valid data (VPAs contain "@" and amount is positive).

**Validates: Requirements 2.5, 2.6**

---

### Property 2: Fraud Probability Percentage Display

*For any* fraud probability value between 0.0 and 1.0, the Risk Gauge SHALL display the value as a percentage by multiplying by 100 and formatting with appropriate precision.

**Validates: Requirements 5.1**

---

### Property 3: Risk Gauge Color Mapping

*For any* fraud probability value, the Risk Gauge SHALL display the correct color: red for probability > 0.70, yellow for probability between 0.40 and 0.70 (inclusive), and green for probability < 0.40.

**Validates: Requirements 5.3, 5.4, 5.5**

---

### Property 4: Execution Time Display Format

*For any* execution time value in milliseconds, the Latency Metric SHALL format the display as "Inference Time: Xms" where X is the execution time value.

**Validates: Requirements 6.1, 6.3**

---

### Property 5: Latency Metric Color Mapping

*For any* execution time value, the Latency Metric SHALL display green color when time < 100ms and yellow color when time >= 100ms.

**Validates: Requirements 6.4, 6.5**

---

### Property 6: Explanation Text Rendering

*For any* non-null explanation string, the XAI Panel SHALL render the complete explanation text in the explanation section.

**Validates: Requirements 7.2**

---

### Property 7: Feature Names Display

*For any* set of SHAP features, the bar chart SHALL display all feature names on the y-axis without omission or truncation.

**Validates: Requirements 8.2**

---

### Property 8: Feature Importance Sorting

*For any* unsorted list of SHAP features, the bar chart SHALL render features in descending order by importance value, with the highest importance at the top.

**Validates: Requirements 8.4**

---

### Property 9: Importance Percentage Formatting

*For any* SHAP feature importance value between 0.0 and 1.0, the chart tooltip SHALL format the value as a percentage by multiplying by 100.

**Validates: Requirements 8.7**

---

### Property 10: VPA Validation

*For any* string input in the VPA fields, the form validation SHALL display an error message if and only if the string does not contain the "@" symbol.

**Validates: Requirements 11.1**

---

### Property 11: Amount Validation

*For any* input in the Amount field, the form validation SHALL display an error message if and only if the value is not a positive number (including zero, negative numbers, or non-numeric strings).

**Validates: Requirements 11.2**

---

### Property 12: Form Submission Prevention

*For any* form state where one or more validation errors exist, the form submission SHALL be prevented and the simulate button SHALL remain disabled.

**Validates: Requirements 11.4**

---

### Property 13: Cross-Viewport Functionality

*For any* viewport width between 320px and 2560px, all core functionality (form input, validation, simulation, results display) SHALL operate correctly without JavaScript errors or missing UI elements.

**Validates: Requirements 10.4**

---

### Property 14: Chart Responsiveness

*For any* viewport width, the SHAP feature importance chart SHALL adjust its dimensions to fit within the container without overflow or horizontal scrolling.

**Validates: Requirements 10.5**

---

### Property 15: Accessibility Labels

*For all* form inputs and visual indicators (badges, gauges, charts), each element SHALL have either an aria-label attribute or descriptive alt text for screen reader accessibility.

**Validates: Requirements 13.2, 13.5**

---

### Property 16: Color Contrast Compliance

*For all* text elements in the dashboard, the color contrast ratio between text and background SHALL meet or exceed 4.5:1 for WCAG AA compliance.

**Validates: Requirements 13.4**

---

## Error Handling

### Client-Side Error Scenarios

#### 1. Form Validation Errors

**Scenario**: User enters invalid VPA or amount

**Handling**:
- Display inline error messages below each invalid field
- Error message format: `<span className="text-red-400 text-sm">Error description</span>`
- Disable submit button until all errors cleared
- Clear error when user corrects input (onChange event)

**Example Error Messages**:
- VPA: "VPA must contain @ symbol (e.g., user@ybl)"
- Amount: "Amount must be a positive number"

---

#### 2. Mock Service Timeout

**Scenario**: Mock service takes longer than expected (future real API integration)

**Handling**:
```typescript
const TIMEOUT_MS = 5000;

async function simulateWithTimeout(input: TransactionInput) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), TIMEOUT_MS);
  
  try {
    const response = await simulateFraudDetection(input);
    clearTimeout(timeoutId);
    return response;
  } catch (error) {
    if (error.name === 'AbortError') {
      throw new Error('Request timed out. Please try again.');
    }
    throw error;
  }
}
```

- Display error message in Evaluation Panel: "Request timed out. Please try again."
- Re-enable submit button for retry
- Log error to console for debugging

---

#### 3. Component Rendering Errors

**Scenario**: React component throws error during render (e.g., chart library issue)

**Handling**:
```typescript
class ErrorBoundary extends React.Component<Props, State> {
  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('Component error:', error, errorInfo);
    this.setState({ hasError: true, error });
  }
  
  render() {
    if (this.state.hasError) {
      return (
        <div className="p-4 bg-red-900/20 border border-red-500 rounded">
          <h3 className="text-red-400 font-bold">Something went wrong</h3>
          <p className="text-gray-400 text-sm">
            Unable to display this component. Please refresh the page.
          </p>
        </div>
      );
    }
    return this.props.children;
  }
}
```

- Wrap XAIPanel in ErrorBoundary (most complex component with chart)
- Display user-friendly error message instead of blank screen
- Preserve rest of application functionality

---

#### 4. Invalid Response Data

**Scenario**: Mock service returns malformed data (preparing for real API)

**Handling**:
```typescript
function validateResponse(data: any): FraudDetectionResponse {
  if (!data.transaction_id || typeof data.transaction_id !== 'string') {
    throw new Error('Invalid response: missing transaction_id');
  }
  if (!['BLOCKED', 'APPROVED'].includes(data.status)) {
    throw new Error('Invalid response: invalid status value');
  }
  if (typeof data.fraud_probability !== 'number' || 
      data.fraud_probability < 0 || 
      data.fraud_probability > 1) {
    throw new Error('Invalid response: fraud_probability out of range');
  }
  // Additional validation...
  return data as FraudDetectionResponse;
}
```

- Display error message: "Invalid response from server. Please try again."
- Log detailed error for debugging
- Allow user to retry simulation

---

### Error State Management

```typescript
interface ErrorState {
  type: 'validation' | 'network' | 'rendering' | 'data';
  message: string;
  field?: string; // For validation errors
  timestamp: number;
}

// In DashboardLayout state
const [error, setError] = useState<ErrorState | null>(null);

// Clear error after 5 seconds for non-validation errors
useEffect(() => {
  if (error && error.type !== 'validation') {
    const timer = setTimeout(() => setError(null), 5000);
    return () => clearTimeout(timer);
  }
}, [error]);
```

---

## Testing Strategy

### Overview

The testing strategy employs a **dual approach** combining property-based testing for universal behaviors with example-based testing for specific scenarios and UI interactions. This ensures comprehensive coverage while maintaining test maintainability.

---

### Property-Based Testing

**Library**: `fast-check` (JavaScript/TypeScript property-based testing library)

**Configuration**: Minimum 100 iterations per property test (to ensure edge case coverage through randomization)

**Tagging Convention**: Each property test includes a comment referencing the design document property:
```typescript
// Feature: finguard-frontend-dashboard, Property 1: Submit Button Enabled State
test('submit button enabled state', () => { ... });
```

#### Property Test Suite

**1. Form Validation Properties** (Properties 1, 10, 11, 12)

```typescript
import fc from 'fast-check';

describe('Form Validation Properties', () => {
  // Feature: finguard-frontend-dashboard, Property 1: Submit Button Enabled State
  test('button enabled iff all fields valid', () => {
    fc.assert(
      fc.property(
        fc.string(), // senderVPA
        fc.string(), // receiverVPA
        fc.float({ min: -1000, max: 1000 }), // amount
        (sender, receiver, amount) => {
          const isValid = 
            sender.includes('@') && 
            receiver.includes('@') && 
            amount > 0;
          
          const buttonEnabled = shouldEnableButton({ sender, receiver, amount });
          
          expect(buttonEnabled).toBe(isValid);
        }
      ),
      { numRuns: 100 }
    );
  });

  // Feature: finguard-frontend-dashboard, Property 10: VPA Validation
  test('VPA validation detects missing @ symbol', () => {
    fc.assert(
      fc.property(
        fc.string(),
        (vpa) => {
          const hasError = !validateVPA(vpa);
          const containsAt = vpa.includes('@');
          
          expect(hasError).toBe(!containsAt);
        }
      ),
      { numRuns: 100 }
    );
  });

  // Feature: finguard-frontend-dashboard, Property 11: Amount Validation
  test('amount validation rejects non-positive values', () => {
    fc.assert(
      fc.property(
        fc.oneof(
          fc.float({ max: 0 }), // zero or negative
          fc.constant('invalid'), // non-numeric
          fc.constant('') // empty
        ),
        (amount) => {
          const hasError = !validateAmount(amount);
          expect(hasError).toBe(true);
        }
      ),
      { numRuns: 100 }
    );
  });

  // Feature: finguard-frontend-dashboard, Property 12: Form Submission Prevention
  test('form submission prevented with validation errors', () => {
    fc.assert(
      fc.property(
        fc.record({
          sender: fc.string().filter(s => !s.includes('@')), // invalid
          receiver: fc.string(),
          amount: fc.float()
        }),
        (input) => {
          const errors = validateTransactionInput(input);
          const canSubmit = Object.keys(errors).length === 0;
          
          expect(canSubmit).toBe(false);
        }
      ),
      { numRuns: 100 }
    );
  });
});
```

---

**2. Display Formatting Properties** (Properties 2, 4, 9)

```typescript
describe('Display Formatting Properties', () => {
  // Feature: finguard-frontend-dashboard, Property 2: Fraud Probability Percentage Display
  test('probability displayed as percentage', () => {
    fc.assert(
      fc.property(
        fc.float({ min: 0, max: 1 }),
        (probability) => {
          const displayed = formatProbabilityAsPercentage(probability);
          const expected = `${(probability * 100).toFixed(0)}%`;
          
          expect(displayed).toBe(expected);
        }
      ),
      { numRuns: 100 }
    );
  });

  // Feature: finguard-frontend-dashboard, Property 4: Execution Time Display Format
  test('execution time formatted correctly', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 10000 }),
        (timeMs) => {
          const displayed = formatLatency(timeMs);
          expect(displayed).toBe(`Inference Time: ${timeMs}ms`);
        }
      ),
      { numRuns: 100 }
    );
  });

  // Feature: finguard-frontend-dashboard, Property 9: Importance Percentage Formatting
  test('SHAP importance formatted as percentage in tooltips', () => {
    fc.assert(
      fc.property(
        fc.float({ min: 0, max: 1 }),
        (importance) => {
          const tooltipValue = formatImportanceForTooltip(importance);
          const expected = `${(importance * 100).toFixed(1)}%`;
          
          expect(tooltipValue).toBe(expected);
        }
      ),
      { numRuns: 100 }
    );
  });
});
```

---

**3. Color Mapping Properties** (Properties 3, 5)

```typescript
describe('Color Mapping Properties', () => {
  // Feature: finguard-frontend-dashboard, Property 3: Risk Gauge Color Mapping
  test('risk gauge color based on probability thresholds', () => {
    fc.assert(
      fc.property(
        fc.float({ min: 0, max: 1 }),
        (probability) => {
          const color = getRiskGaugeColor(probability);
          
          if (probability > 0.70) {
            expect(color).toBe('red');
          } else if (probability >= 0.40) {
            expect(color).toBe('yellow');
          } else {
            expect(color).toBe('green');
          }
        }
      ),
      { numRuns: 100 }
    );
  });

  // Feature: finguard-frontend-dashboard, Property 5: Latency Metric Color Mapping
  test('latency metric color based on 100ms threshold', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 500 }),
        (timeMs) => {
          const color = getLatencyColor(timeMs);
          
          if (timeMs < 100) {
            expect(color).toBe('green');
          } else {
            expect(color).toBe('yellow');
          }
        }
      ),
      { numRuns: 100 }
    );
  });
});
```

---

**4. Data Display Properties** (Properties 6, 7, 8)

```typescript
describe('Data Display Properties', () => {
  // Feature: finguard-frontend-dashboard, Property 6: Explanation Text Rendering
  test('explanation text rendered completely', () => {
    fc.assert(
      fc.property(
        fc.string({ minLength: 10, maxLength: 500 }),
        (explanation) => {
          const { getByText } = render(
            <XAIPanel explanation={explanation} shapFeatures={[]} />
          );
          
          expect(getByText(explanation)).toBeInTheDocument();
        }
      ),
      { numRuns: 100 }
    );
  });

  // Feature: finguard-frontend-dashboard, Property 7: Feature Names Display
  test('all feature names displayed on y-axis', () => {
    fc.assert(
      fc.property(
        fc.array(
          fc.record({
            feature: fc.string({ minLength: 5, maxLength: 30 }),
            importance: fc.float({ min: 0, max: 1 })
          }),
          { minLength: 1, maxLength: 10 }
        ),
        (features) => {
          const { container } = render(<SHAPChart features={features} />);
          
          features.forEach(f => {
            expect(container.textContent).toContain(f.feature);
          });
        }
      ),
      { numRuns: 100 }
    );
  });

  // Feature: finguard-frontend-dashboard, Property 8: Feature Importance Sorting
  test('features sorted by importance descending', () => {
    fc.assert(
      fc.property(
        fc.array(
          fc.record({
            feature: fc.string(),
            importance: fc.float({ min: 0, max: 1 })
          }),
          { minLength: 2, maxLength: 10 }
        ),
        (features) => {
          const sorted = sortFeaturesByImportance(features);
          
          for (let i = 0; i < sorted.length - 1; i++) {
            expect(sorted[i].importance).toBeGreaterThanOrEqual(
              sorted[i + 1].importance
            );
          }
        }
      ),
      { numRuns: 100 }
    );
  });
});
```

---

**5. Responsive Design Properties** (Properties 13, 14)

```typescript
describe('Responsive Design Properties', () => {
  // Feature: finguard-frontend-dashboard, Property 13: Cross-Viewport Functionality
  test('functionality works across viewport widths', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 320, max: 2560 }),
        (viewportWidth) => {
          global.innerWidth = viewportWidth;
          window.dispatchEvent(new Event('resize'));
          
          const { getByPlaceholderText, getByText } = render(<Dashboard />);
          
          // Verify form elements exist
          expect(getByPlaceholderText(/sender vpa/i)).toBeInTheDocument();
          expect(getByPlaceholderText(/receiver vpa/i)).toBeInTheDocument();
          expect(getByPlaceholderText(/amount/i)).toBeInTheDocument();
          expect(getByText(/simulate transaction/i)).toBeInTheDocument();
        }
      ),
      { numRuns: 100 }
    );
  });

  // Feature: finguard-frontend-dashboard, Property 14: Chart Responsiveness
  test('chart adjusts dimensions for viewport', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 320, max: 2560 }),
        (viewportWidth) => {
          global.innerWidth = viewportWidth;
          
          const features = [
            { feature: 'Test', importance: 0.5 }
          ];
          
          const { container } = render(<SHAPChart features={features} />);
          const chartContainer = container.querySelector('.recharts-wrapper');
          
          // Chart should not exceed viewport width
          expect(chartContainer.offsetWidth).toBeLessThanOrEqual(viewportWidth);
        }
      ),
      { numRuns: 100 }
    );
  });
});
```

---

**6. Accessibility Properties** (Properties 15, 16)

```typescript
describe('Accessibility Properties', () => {
  // Feature: finguard-frontend-dashboard, Property 15: Accessibility Labels
  test('all interactive elements have aria labels', () => {
    fc.assert(
      fc.property(
        fc.constant(null), // No random input needed
        () => {
          const { container } = render(<Dashboard />);
          
          // Query all inputs, buttons, and visual indicators
          const inputs = container.querySelectorAll('input');
          const buttons = container.querySelectorAll('button');
          const badges = container.querySelectorAll('[data-testid*="badge"]');
          
          [...inputs, ...buttons, ...badges].forEach(element => {
            const hasLabel = 
              element.hasAttribute('aria-label') ||
              element.hasAttribute('aria-labelledby') ||
              element.hasAttribute('alt');
            
            expect(hasLabel).toBe(true);
          });
        }
      ),
      { numRuns: 100 }
    );
  });

  // Feature: finguard-frontend-dashboard, Property 16: Color Contrast Compliance
  test('text color contrast meets WCAG AA', () => {
    fc.assert(
      fc.property(
        fc.constant(null),
        () => {
          const { container } = render(<Dashboard />);
          
          // Get all text elements
          const textElements = container.querySelectorAll('h1, h2, h3, p, span, label');
          
          textElements.forEach(element => {
            const styles = window.getComputedStyle(element);
            const textColor = styles.color;
            const bgColor = styles.backgroundColor;
            
            const contrastRatio = calculateContrastRatio(textColor, bgColor);
            
            // WCAG AA requires 4.5:1 for normal text
            expect(contrastRatio).toBeGreaterThanOrEqual(4.5);
          });
        }
      ),
      { numRuns: 100 }
    );
  });
});
```

---

### Example-Based Unit Testing

**Library**: Vitest + React Testing Library

**Purpose**: Test specific scenarios, UI interactions, and integration flows that are not universal properties.

#### Unit Test Suite

**1. Component Structure Tests** (Requirements 1.1-1.4, 2.1-2.4)

```typescript
describe('Dashboard Structure', () => {
  test('renders header with title and subtitle', () => {
    const { getByText } = render(<Dashboard />);
    
    expect(getByText('FinGuard')).toBeInTheDocument();
    expect(getByText(/Real-Time UPI Fraud Detection Engine/i)).toBeInTheDocument();
  });

  test('renders transaction simulator on left', () => {
    const { container } = render(<Dashboard />);
    const layout = container.querySelector('.dashboard-layout');
    const simulator = layout.querySelector('.transaction-simulator');
    
    expect(simulator).toBeInTheDocument();
    // Verify left positioning via CSS class or flex order
  });

  test('renders evaluation panel on right', () => {
    const { container } = render(<Dashboard />);
    const layout = container.querySelector('.dashboard-layout');
    const panel = layout.querySelector('.evaluation-panel');
    
    expect(panel).toBeInTheDocument();
  });

  test('form contains all required inputs', () => {
    const { getByLabelText } = render(<TransactionSimulator />);
    
    expect(getByLabelText(/sender vpa/i)).toBeInTheDocument();
    expect(getByLabelText(/receiver vpa/i)).toBeInTheDocument();
    expect(getByLabelText(/amount/i)).toBeInTheDocument();
  });
});
```

---

**2. Mock Service Integration Tests** (Requirements 3.1-3.4)

```typescript
describe('Mock Service Integration', () => {
  test('displays loading spinner during simulation', async () => {
    const { getByText, getByTestId } = render(<Dashboard />);
    
    const button = getByText(/simulate transaction/i);
    fireEvent.click(button);
    
    expect(getByTestId('loading-spinner')).toBeInTheDocument();
  });

  test('waits 50ms before returning response', async () => {
    const startTime = Date.now();
    
    await simulateFraudDetection({
      senderVPA: 'test@ybl',
      receiverVPA: 'merchant@paytm',
      amount: 100
    });
    
    const endTime = Date.now();
    const elapsed = endTime - startTime;
    
    expect(elapsed).toBeGreaterThanOrEqual(50);
  });

  test('returns hardcoded response structure', async () => {
    const response = await simulateFraudDetection({
      senderVPA: 'test@ybl',
      receiverVPA: 'merchant@paytm',
      amount: 100
    });
    
    expect(response.transaction_id).toBe('tx-987654321');
    expect(response.status).toBe('BLOCKED');
    expect(response.fraud_probability).toBe(0.92);
    expect(response.execution_time_ms).toBe(42);
    expect(response.shap_features).toHaveLength(4);
  });

  test('updates evaluation panel after response', async () => {
    const { getByText, findByText } = render(<Dashboard />);
    
    // Fill form
    fireEvent.change(getByLabelText(/sender vpa/i), { target: { value: 'test@ybl' } });
    fireEvent.change(getByLabelText(/receiver vpa/i), { target: { value: 'merchant@paytm' } });
    fireEvent.change(getByLabelText(/amount/i), { target: { value: '100' } });
    
    // Submit
    fireEvent.click(getByText(/simulate transaction/i));
    
    // Wait for results
    expect(await findByText(/TRANSACTION BLOCKED/i)).toBeInTheDocument();
  });
});
```

---

**3. Status Badge Tests** (Requirements 4.1-4.5)

```typescript
describe('Status Badge Display', () => {
  test('shows red badge for BLOCKED status', () => {
    const { getByText } = render(
      <EvaluationPanel 
        results={{ status: 'BLOCKED', ...mockResults }} 
        isLoading={false} 
      />
    );
    
    const badge = getByText(/TRANSACTION BLOCKED/i);
    expect(badge).toHaveClass('bg-red-500'); // or similar red styling
  });

  test('shows green badge for APPROVED status', () => {
    const { getByText } = render(
      <EvaluationPanel 
        results={{ status: 'APPROVED', ...mockResults }} 
        isLoading={false} 
      />
    );
    
    const badge = getByText(/APPROVED/i);
    expect(badge).toHaveClass('bg-green-500');
  });

  test('badge appears at top of results section', () => {
    const { container } = render(
      <EvaluationPanel results={mockResults} isLoading={false} />
    );
    
    const resultsSection = container.querySelector('.results');
    const badge = resultsSection.querySelector('.status-badge');
    
    // First child or top positioning
    expect(resultsSection.firstChild).toContain(badge);
  });

  test('shows placeholder when no simulation run', () => {
    const { getByText } = render(
      <EvaluationPanel results={null} isLoading={false} />
    );
    
    expect(getByText(/awaiting input/i)).toBeInTheDocument();
  });
});
```

---

**4. Loading State Tests** (Requirements 12.1-12.5)

```typescript
describe('Loading State Management', () => {
  test('disables submit button during simulation', async () => {
    const { getByText } = render(<Dashboard />);
    
    const button = getByText(/simulate transaction/i);
    fireEvent.click(button);
    
    expect(button).toBeDisabled();
  });

  test('shows loading spinner during simulation', async () => {
    const { getByTestId, getByText } = render(<Dashboard />);
    
    fireEvent.click(getByText(/simulate transaction/i));
    
    expect(getByTestId('loading-spinner')).toBeInTheDocument();
  });

  test('hides previous results during new simulation', async () => {
    const { getByText, queryByText, findByText } = render(<Dashboard />);
    
    // First simulation
    fireEvent.click(getByText(/simulate transaction/i));
    await findByText(/TRANSACTION BLOCKED/i);
    
    // Second simulation
    fireEvent.click(getByText(/simulate transaction/i));
    
    // Results should be hidden
    expect(queryByText(/TRANSACTION BLOCKED/i)).not.toBeInTheDocument();
  });

  test('re-enables button after completion', async () => {
    const { getByText, findByText } = render(<Dashboard />);
    
    const button = getByText(/simulate transaction/i);
    fireEvent.click(button);
    
    await findByText(/TRANSACTION BLOCKED/i);
    
    expect(button).not.toBeDisabled();
  });

  test('hides spinner and shows results after completion', async () => {
    const { getByText, getByTestId, findByText, queryByTestId } = render(<Dashboard />);
    
    fireEvent.click(getByText(/simulate transaction/i));
    
    await findByText(/TRANSACTION BLOCKED/i);
    
    expect(queryByTestId('loading-spinner')).not.toBeInTheDocument();
  });
});
```

---

**5. Responsive Layout Tests** (Requirements 10.1-10.3)

```typescript
describe('Responsive Layout', () => {
  test('side-by-side layout at 1024px+', () => {
    global.innerWidth = 1200;
    window.dispatchEvent(new Event('resize'));
    
    const { container } = render(<Dashboard />);
    const layout = container.querySelector('.dashboard-layout');
    
    // Check for flex-row or grid-cols-2
    expect(layout).toHaveClass(/flex-row|grid-cols-2/);
  });

  test('stacked layout below 1024px', () => {
    global.innerWidth = 800;
    window.dispatchEvent(new Event('resize'));
    
    const { container } = render(<Dashboard />);
    const layout = container.querySelector('.dashboard-layout');
    
    // Check for flex-col or grid-cols-1
    expect(layout).toHaveClass(/flex-col|grid-cols-1/);
  });

  test('mobile styles applied below 768px', () => {
    global.innerWidth = 375;
    window.dispatchEvent(new Event('resize'));
    
    const { container } = render(<Dashboard />);
    
    // Check for mobile text sizes and spacing
    const header = container.querySelector('h1');
    const styles = window.getComputedStyle(header);
    
    // Expecting smaller font size on mobile
    expect(parseInt(styles.fontSize)).toBeLessThan(48); // Desktop is ~48px (text-4xl)
  });
});
```

---

**6. Accessibility Tests** (Requirements 13.1, 13.3)

```typescript
describe('Accessibility Features', () => {
  test('supports keyboard navigation', () => {
    const { getByLabelText, getByText } = render(<Dashboard />);
    
    const senderInput = getByLabelText(/sender vpa/i);
    senderInput.focus();
    
    // Tab to next field
    fireEvent.keyDown(senderInput, { key: 'Tab' });
    
    const receiverInput = getByLabelText(/receiver vpa/i);
    expect(document.activeElement).toBe(receiverInput);
  });

  test('evaluation panel has aria-live region', () => {
    const { container } = render(<Dashboard />);
    const evaluationPanel = container.querySelector('.evaluation-panel');
    
    expect(evaluationPanel).toHaveAttribute('aria-live', 'polite');
  });

  test('disabled button shows tooltip', async () => {
    const { getByText, findByRole } = render(<Dashboard />);
    
    const button = getByText(/simulate transaction/i);
    
    // Button should be disabled initially (empty form)
    expect(button).toBeDisabled();
    
    // Hover to show tooltip
    fireEvent.mouseOver(button);
    
    const tooltip = await findByRole('tooltip');
    expect(tooltip).toHaveTextContent(/fill all fields/i);
  });
});
```

---

### Visual Regression Testing

**Tool**: Percy.io or Chromatic

**Purpose**: Catch unintended visual changes in UI components

**Test Cases**:
1. Dashboard initial state (empty form)
2. Form with validation errors
3. Evaluation panel with BLOCKED result
4. Evaluation panel with APPROVED result
5. XAI panel with SHAP chart
6. Loading state
7. Mobile viewport (375px)
8. Tablet viewport (768px)
9. Desktop viewport (1440px)

```typescript
describe('Visual Regression', () => {
  test('captures dashboard states', async () => {
    const { container } = render(<Dashboard />);
    
    // Capture initial state
    await percySnapshot('Dashboard - Initial');
    
    // Fill form with errors
    fireEvent.change(getByLabelText(/sender vpa/i), { target: { value: 'invalid' } });
    await percySnapshot('Dashboard - Validation Errors');
    
    // Fill valid form and simulate
    fireEvent.change(getByLabelText(/sender vpa/i), { target: { value: 'test@ybl' } });
    fireEvent.click(getByText(/simulate transaction/i));
    await percySnapshot('Dashboard - Loading');
    
    // Wait for results
    await findByText(/TRANSACTION BLOCKED/i);
    await percySnapshot('Dashboard - Results');
  });
});
```

---

### Integration Testing Strategy

**Scope**: End-to-end user flows

**Test Scenarios**:

1. **Complete Fraud Detection Flow**
   - User enters valid transaction details
   - Clicks simulate button
   - Sees loading state
   - Views fraud detection results
   - Reads XAI explanation
   - Examines SHAP chart

2. **Form Validation Flow**
   - User enters invalid VPA (no @)
   - Sees validation error
   - Corrects input
   - Error clears
   - Submit button enables

3. **Responsive Behavior Flow**
   - Desktop user sees side-by-side layout
   - Resizes to tablet
   - Layout adjusts to stacked
   - Resizes to mobile
   - All functionality still works

---

### Test Coverage Goals

- **Unit Test Coverage**: 80%+ for utility functions and components
- **Integration Test Coverage**: 70%+ for user flows
- **Property Test Coverage**: 100% of correctness properties (16 properties)
- **Visual Regression**: Key UI states captured (9 snapshots minimum)
- **Accessibility**: 100% of WCAG AA Level criteria for applicable components

---

### Continuous Integration

**Pipeline Configuration** (GitHub Actions example):

```yaml
name: Test Suite

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-node@v3
        with:
          node-version: '18'
      
      - name: Install dependencies
        run: npm ci
      
      - name: Run unit tests
        run: npm run test:unit
      
      - name: Run property tests
        run: npm run test:property
      
      - name: Run integration tests
        run: npm run test:integration
      
      - name: Check accessibility
        run: npm run test:a11y
      
      - name: Generate coverage report
        run: npm run test:coverage
      
      - name: Upload coverage to Codecov
        uses: codecov/codecov-action@v3
```

---

## Implementation Guidance

### Project Structure

```
finguard-frontend/
├── src/
│   ├── components/
│   │   ├── Header.tsx
│   │   ├── DashboardLayout.tsx
│   │   ├── TransactionSimulator.tsx
│   │   ├── InputField.tsx
│   │   ├── EvaluationPanel.tsx
│   │   ├── StatusBadge.tsx
│   │   ├── RiskGauge.tsx
│   │   ├── LatencyMetric.tsx
│   │   ├── LoadingSpinner.tsx
│   │   ├── XAIPanel.tsx
│   │   ├── ExplanationText.tsx
│   │   ├── SHAPChart.tsx
│   │   └── ErrorBoundary.tsx
│   ├── services/
│   │   └── mockFraudService.ts
│   ├── types/
│   │   └── index.ts
│   ├── utils/
│   │   ├── validation.ts
│   │   ├── formatting.ts
│   │   └── colorMapping.ts
│   ├── hooks/
│   │   ├── useFormValidation.ts
│   │   └── useFraudSimulation.ts
│   ├── App.tsx
│   ├── main.tsx
│   └── index.css
├── tests/
│   ├── unit/
│   │   ├── components/
│   │   ├── services/
│   │   └── utils/
│   ├── properties/
│   │   ├── validation.property.test.ts
│   │   ├── formatting.property.test.ts
│   │   ├── colorMapping.property.test.ts
│   │   ├── display.property.test.ts
│   │   ├── responsive.property.test.ts
│   │   └── accessibility.property.test.ts
│   ├── integration/
│   │   └── fraudDetectionFlow.test.ts
│   └── visual/
│       └── dashboard.visual.test.ts
├── public/
├── package.json
├── tsconfig.json
├── vite.config.ts
├── tailwind.config.js
├── postcss.config.js
└── README.md
```

---

### Development Phases

#### Phase 1: Project Setup and Core Infrastructure (Week 1)

**Tasks**:
1. Initialize Vite + React + TypeScript project
2. Configure Tailwind CSS with custom theme (dark mode colors)
3. Set up ESLint and Prettier
4. Define TypeScript interfaces in `types/index.ts`
5. Create mock service with hardcoded response
6. Set up testing infrastructure (Vitest, React Testing Library, fast-check)

**Deliverables**:
- Project builds successfully
- Mock service returns expected response
- Basic test setup verified

---

#### Phase 2: Core Components (Week 2)

**Tasks**:
1. Implement Header component
2. Implement DashboardLayout with responsive grid
3. Implement TransactionSimulator with InputField components
4. Implement form validation logic
5. Create custom hooks: `useFormValidation`, `useFraudSimulation`
6. Write unit tests for components and validation logic

**Deliverables**:
- Functional form with validation
- Form submits and calls mock service
- Unit tests passing (80%+ coverage)

---

#### Phase 3: Results Display Components (Week 3)

**Tasks**:
1. Implement EvaluationPanel with conditional rendering
2. Implement StatusBadge with color logic
3. Implement RiskGauge using Recharts/circular progress
4. Implement LatencyMetric with color mapping
5. Implement LoadingSpinner with animations
6. Write unit tests for results components

**Deliverables**:
- Results display after simulation
- Visual elements render correctly
- Loading states work properly
- Unit tests passing

---

#### Phase 4: XAI Visualization (Week 4)

**Tasks**:
1. Implement XAIPanel layout
2. Implement ExplanationText component
3. Implement SHAPChart using Recharts horizontal bar chart
4. Add sorting and color gradient logic for features
5. Implement responsive chart sizing
6. Write unit tests for XAI components

**Deliverables**:
- SHAP chart displays feature importances
- Explanation text renders correctly
- Chart is responsive
- Unit tests passing

---

#### Phase 5: Property-Based Testing (Week 5)

**Tasks**:
1. Set up fast-check configuration
2. Write property tests for validation logic (Properties 1, 10, 11, 12)
3. Write property tests for display formatting (Properties 2, 4, 9)
4. Write property tests for color mapping (Properties 3, 5)
5. Write property tests for data display (Properties 6, 7, 8)
6. Write property tests for responsiveness (Properties 13, 14)
7. Write property tests for accessibility (Properties 15, 16)

**Deliverables**:
- All 16 properties tested with 100+ iterations each
- Property tests passing
- Coverage report showing property coverage

---

#### Phase 6: Integration and Polish (Week 6)

**Tasks**:
1. Write integration tests for complete user flows
2. Set up visual regression testing (Percy/Chromatic)
3. Accessibility audit using axe-core
4. Performance optimization (lazy loading, memoization)
5. Error boundary implementation
6. Documentation (README, component docs)

**Deliverables**:
- Integration tests passing
- Visual regression baseline captured
- Accessibility compliance verified
- Performance metrics acceptable
- Complete documentation

---

### Technology Stack Details

#### Core Dependencies

```json
{
  "dependencies": {
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "recharts": "^2.10.0",
    "framer-motion": "^10.16.0"
  },
  "devDependencies": {
    "@types/react": "^18.2.0",
    "@types/react-dom": "^18.2.0",
    "@vitejs/plugin-react": "^4.2.0",
    "typescript": "^5.3.0",
    "vite": "^5.0.0",
    "vitest": "^1.0.0",
    "@testing-library/react": "^14.1.0",
    "@testing-library/user-event": "^14.5.0",
    "fast-check": "^3.15.0",
    "tailwindcss": "^3.4.0",
    "postcss": "^8.4.0",
    "autoprefixer": "^10.4.0",
    "eslint": "^8.55.0",
    "prettier": "^3.1.0",
    "@axe-core/react": "^4.8.0"
  }
}
```

---

#### Tailwind Configuration

```javascript
// tailwind.config.js
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        'cyber-dark': '#0a0e27',
        'cyber-blue': '#06b6d4',
        'cyber-purple': '#8b5cf6',
        'cyber-red': '#ef4444',
        'cyber-green': '#10b981',
        'cyber-yellow': '#f59e0b',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['Fira Code', 'monospace'],
      },
      boxShadow: {
        'neon': '0 0 20px rgba(6, 182, 212, 0.5)',
        'neon-strong': '0 0 30px rgba(6, 182, 212, 0.8)',
      },
    },
  },
  plugins: [],
};
```

---

#### Vite Configuration

```typescript
// vite.config.ts
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './tests/setup.ts',
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
      exclude: [
        'node_modules/',
        'tests/',
        '**/*.d.ts',
        '**/*.config.*',
        '**/mockData.ts',
      ],
    },
  },
});
```

---

### Performance Considerations

1. **Code Splitting**: Lazy load XAIPanel since it contains heavy chart library
   ```typescript
   const XAIPanel = lazy(() => import('./components/XAIPanel'));
   ```

2. **Memoization**: Memoize expensive calculations
   ```typescript
   const sortedFeatures = useMemo(
     () => sortFeaturesByImportance(shapFeatures),
     [shapFeatures]
   );
   ```

3. **Debouncing**: Debounce validation on input change
   ```typescript
   const debouncedValidation = useMemo(
     () => debounce(validateField, 300),
     []
   );
   ```

4. **Chart Performance**: Limit chart data points if needed
   - Max 10 features in SHAP chart (truncate rest)
   - Use ResponsiveContainer for optimal rendering

---

### Security Considerations

1. **Input Sanitization**: Although currently mock, prepare for real backend
   ```typescript
   function sanitizeInput(value: string): string {
     return value.trim().replace(/[<>]/g, '');
   }
   ```

2. **XSS Prevention**: React automatically escapes, but be cautious with dangerouslySetInnerHTML
   - Do NOT use dangerouslySetInnerHTML for explanation text
   - Use text content only

3. **API Communication**: When integrating real backend
   - Use HTTPS only
   - Implement CORS properly
   - Add request/response validation
   - Implement rate limiting on client side

---

### Future Backend Integration

When Spring Boot backend is ready, replace mock service:

```typescript
// services/fraudService.ts (future implementation)
export async function detectFraud(
  input: TransactionInput
): Promise<FraudDetectionResponse> {
  const response = await fetch('https://api.finguard.com/v1/detect', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${getAuthToken()}`,
    },
    body: JSON.stringify({
      sender_vpa: input.senderVPA,
      receiver_vpa: input.receiverVPA,
      amount: input.amount,
      timestamp: new Date().toISOString(),
    }),
  });

  if (!response.ok) {
    throw new Error(`API error: ${response.status}`);
  }

  const data = await response.json();
  return validateResponse(data);
}
```

**Migration Steps**:
1. Add environment variable for API endpoint
2. Replace mockFraudService import with real fraudService
3. Add error handling for network failures
4. Add retry logic for transient failures
5. Update loading time (remove artificial 50ms delay)
6. Add authentication token management

---

### Deployment Strategy

**Build for Production**:
```bash
npm run build
```

**Hosting Options**:
1. **Vercel**: Zero-config deployment, automatic HTTPS
2. **Netlify**: Great for static sites, easy rollbacks
3. **AWS S3 + CloudFront**: Scalable, cost-effective
4. **GitHub Pages**: Free for public repos

**Build Optimization**:
- Minification and tree-shaking (handled by Vite)
- Asset optimization (images, fonts)
- Gzip/Brotli compression
- CDN for static assets

**Environment Configuration**:
```typescript
// .env.production
VITE_API_ENDPOINT=https://api.finguard.com
VITE_API_VERSION=v1
VITE_ENABLE_ANALYTICS=true
```

---

## Conclusion

This design document provides a comprehensive blueprint for implementing the FinGuard Frontend Dashboard. The architecture emphasizes modularity, testability, and maintainability through:

- Clear component hierarchy with single responsibilities
- Comprehensive property-based testing for universal behaviors
- Example-based testing for specific scenarios
- Accessibility-first approach
- Progressive enhancement for responsiveness
- Error handling and resilience
- Future-proof design for backend integration

The dual testing approach (property-based + example-based) ensures both correctness across input spaces and proper handling of specific user flows. The phased implementation plan provides a clear path from setup through deployment, with concrete deliverables at each stage.

