# Implementation Plan: FinGuard Frontend Dashboard

## Overview

This implementation plan breaks down the FinGuard Frontend Dashboard into discrete coding tasks. The dashboard is a React-based web application with TypeScript that provides an interactive interface for simulating and visualizing UPI fraud detection. The implementation follows a component-based architecture with a mock service layer, progressive enhancement for responsive design, and comprehensive testing including property-based tests for universal correctness properties.

## Tasks

- [x] 1. Initialize project structure and development environment
  - Create Vite + React + TypeScript project with `npm create vite@latest`
  - Configure Tailwind CSS with custom dark-mode theme (cyber colors)
  - Set up ESLint and Prettier for code quality
  - Configure Vitest and React Testing Library for unit tests
  - Install and configure fast-check for property-based testing
  - Install dependencies: recharts, framer-motion, @axe-core/react
  - Create project directory structure (components/, services/, types/, utils/, hooks/, tests/)
  - Configure TypeScript with strict mode enabled
  - Set up Vite configuration with test environment settings
  - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6_

- [ ] 2. Define TypeScript interfaces and mock service
  - [-] 2.1 Create TypeScript type definitions
    - Define `TransactionInput` interface (senderVPA, receiverVPA, amount)
    - Define `FraudDetectionResponse` interface (transaction_id, status, fraud_probability, execution_time_ms, xai_explanation, shap_features)
    - Define `SHAPFeature` interface (feature, importance)
    - Define `ValidationErrors` interface
    - Define `DashboardState` interface
    - _Requirements: All requirements depend on these types_
  
  - [-] 2.2 Implement mock fraud detection service
    - Create `mockFraudService.ts` in services folder
    - Implement `simulateFraudDetection()` function with 50ms delay
    - Return hardcoded JSON response with transaction_id "tx-987654321", status "BLOCKED", fraud_probability 0.92, execution_time_ms 42
    - Include 4 SHAP features in response (Receiver VPA Age: 0.45, Time Since Last Txn: 0.30, Transaction Amount: 0.17, Location Delta: 0.08)
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [ ] 3. Implement validation and utility functions
  - [ ] 3.1 Create validation utility functions
    - Implement `validateVPA()` function to check for "@" symbol
    - Implement `validateAmount()` function to check for positive number
    - Implement `validateTransactionInput()` function to validate complete form
    - Export validation functions from utils/validation.ts
    - _Requirements: 11.1, 11.2_
  
  - [ ]* 3.2 Write property tests for validation logic
    - **Property 1: Submit Button Enabled State** - Button enabled iff all fields valid
    - **Property 10: VPA Validation** - Error displayed iff "@" missing
    - **Property 11: Amount Validation** - Error displayed iff non-positive
    - **Property 12: Form Submission Prevention** - Submit prevented with validation errors
    - Use fast-check with 100+ iterations per property
    - _Validates: Requirements 2.5, 2.6, 11.1, 11.2, 11.4_
  
  - [ ] 3.3 Create formatting utility functions
    - Implement `formatProbabilityAsPercentage()` to convert 0.0-1.0 to percentage string
    - Implement `formatLatency()` to format execution time as "Inference Time: Xms"
    - Implement `formatImportanceForTooltip()` to format SHAP importance as percentage
    - Export formatting functions from utils/formatting.ts
    - _Requirements: 5.1, 6.1, 6.3, 8.7_
  
  - [ ]* 3.4 Write property tests for formatting functions
    - **Property 2: Fraud Probability Percentage Display** - Probability displayed as percentage
    - **Property 4: Execution Time Display Format** - Time formatted as "Inference Time: Xms"
    - **Property 9: Importance Percentage Formatting** - SHAP importance formatted as percentage
    - Use fast-check with 100+ iterations per property
    - _Validates: Requirements 5.1, 6.1, 6.3, 8.7_
  
  - [ ] 3.5 Create color mapping utility functions
    - Implement `getRiskGaugeColor()` with thresholds (red >0.70, yellow 0.40-0.70, green <0.40)
    - Implement `getLatencyColor()` with threshold (green <100ms, yellow ≥100ms)
    - Export color mapping functions from utils/colorMapping.ts
    - _Requirements: 5.3, 5.4, 5.5, 6.4, 6.5_
  
  - [ ]* 3.6 Write property tests for color mapping functions
    - **Property 3: Risk Gauge Color Mapping** - Correct color for any probability value
    - **Property 5: Latency Metric Color Mapping** - Correct color for any execution time
    - Use fast-check with 100+ iterations per property
    - _Validates: Requirements 5.3, 5.4, 5.5, 6.4, 6.5_

- [ ] 4. Implement core UI components - Header and Layout
  - [ ] 4.1 Create Header component
    - Render dark-themed header with cyan border-bottom
    - Display "FinGuard" title in cyan-400 color with 4xl font size
    - Display "Real-Time UPI Fraud Detection Engine" subtitle in gray-400
    - Apply padding and styling for modern high-tech aesthetic
    - _Requirements: 1.1, 1.5_
  
  - [ ] 4.2 Create DashboardLayout component
    - Implement responsive grid layout using Tailwind CSS
    - Desktop (≥1024px): side-by-side layout with TransactionSimulator on left, EvaluationPanel on right
    - Tablet/Mobile (<1024px): stacked layout with TransactionSimulator on top
    - Position XAIPanel below the main panels spanning full width
    - Apply dark-mode background colors throughout
    - _Requirements: 1.2, 1.3, 1.4, 1.5, 10.1, 10.2_
  
  - [ ]* 4.3 Write unit tests for Header and Layout components
    - Test Header renders title and subtitle
    - Test DashboardLayout renders all three panel sections
    - Test responsive layout changes at 1024px breakpoint
    - Test dark-mode theme classes applied
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 10.1, 10.2_

- [ ] 5. Checkpoint - Verify project setup and basic structure
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 6. Implement form components and validation
  - [ ] 6.1 Create InputField component
    - Accept props: label, value, onChange, error, placeholder, type
    - Render input with Tailwind styling for dark theme
    - Display error message below input in red-400 color when error exists
    - Apply ARIA labels for accessibility
    - Support keyboard navigation
    - _Requirements: 2.1, 2.2, 2.3, 2.7, 11.1, 11.2, 11.3, 13.1, 13.2_
  
  - [ ] 6.2 Create useFormValidation custom hook
    - Manage form state for senderVPA, receiverVPA, amount fields
    - Track validation errors per field
    - Provide validation trigger function
    - Clear errors when user corrects input (onChange)
    - Return form values, errors, and helper functions
    - _Requirements: 2.5, 2.6, 11.3, 11.4_
  
  - [ ] 6.3 Create TransactionSimulator component
    - Use useFormValidation hook for state management
    - Render three InputField components for Sender VPA, Receiver VPA, and Amount
    - Add placeholder text with example values (e.g., "user@ybl", "500")
    - Implement "Simulate Transaction" button
    - Disable button when any field is empty or has validation errors
    - Call onSimulate callback with validated data on submit
    - Disable form during loading (isLoading prop)
    - Add tooltip on disabled button explaining why
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 11.4, 11.5, 12.1_
  
  - [ ]* 6.4 Write unit tests for form components
    - Test InputField displays label, value, and error message
    - Test TransactionSimulator renders all three input fields
    - Test form validation errors appear for invalid inputs
    - Test button disabled state when fields empty or invalid
    - Test button enabled when all fields valid
    - Test form submission calls onSimulate callback
    - _Requirements: 2.1-2.7, 11.1-11.5_

- [ ] 7. Implement loading and status display components
  - [ ] 7.1 Create LoadingSpinner component
    - Render centered spinner using Tailwind animation utilities
    - Use cyan-500 color for spinner border
    - Apply spin animation with appropriate timing
    - Center within container using flex utilities
    - Add data-testid for testing
    - _Requirements: 3.1, 12.2, 12.3_
  
  - [ ] 7.2 Create StatusBadge component
    - Accept status prop ("BLOCKED" | "APPROVED")
    - Render red badge with "TRANSACTION BLOCKED" text for BLOCKED status
    - Render green badge with "APPROVED" text for APPROVED status
    - Apply high contrast styling for visibility
    - Position prominently at top of results section
    - _Requirements: 4.1, 4.2, 4.3, 4.4_
  
  - [ ]* 7.3 Write unit tests for loading and status components
    - Test LoadingSpinner renders with correct styling
    - Test StatusBadge displays red badge for BLOCKED status
    - Test StatusBadge displays green badge for APPROVED status
    - Test StatusBadge styling for visibility and contrast
    - _Requirements: 3.1, 4.1, 4.2, 4.3, 4.4, 12.2, 12.3_

- [ ] 8. Implement risk visualization components
  - [ ] 8.1 Create RiskGauge component
    - Accept probability prop (0.0 to 1.0)
    - Render circular progress indicator using recharts or custom SVG
    - Display percentage value in center (multiply probability by 100)
    - Apply color based on probability: red >0.70, yellow 0.40-0.70, green <0.40
    - Animate from 0 to target percentage using Framer Motion
    - Apply 1 second animation duration
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_
  
  - [ ] 8.2 Create LatencyMetric component
    - Accept executionTimeMs prop
    - Display as small badge near RiskGauge
    - Format text as "Inference Time: Xms" using formatLatency utility
    - Apply green color when time <100ms, yellow when ≥100ms
    - Use appropriate badge styling with padding and rounded corners
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_
  
  - [ ]* 8.3 Write unit tests for risk visualization components
    - Test RiskGauge displays percentage value correctly
    - Test RiskGauge color changes based on probability thresholds
    - Test RiskGauge animation triggers
    - Test LatencyMetric displays formatted time string
    - Test LatencyMetric color changes based on time threshold
    - _Requirements: 5.1-5.6, 6.1-6.5_

- [ ] 9. Implement EvaluationPanel component
  - [ ] 9.1 Create EvaluationPanel component
    - Accept isLoading and results props
    - Render LoadingSpinner when isLoading is true
    - Render placeholder text "Awaiting input..." when results is null and not loading
    - When results exist and not loading: render StatusBadge, RiskGauge, and LatencyMetric
    - Apply flex layout with appropriate spacing
    - Add aria-live region for accessibility
    - _Requirements: 3.1, 3.4, 4.5, 5.1-5.6, 6.1-6.5, 12.2, 12.3, 12.4, 13.3_
  
  - [ ]* 9.2 Write unit tests for EvaluationPanel
    - Test displays loading spinner when isLoading is true
    - Test displays placeholder when results is null
    - Test displays results components when results exist
    - Test hides previous results during new simulation
    - Test aria-live attribute present for accessibility
    - _Requirements: 3.1, 3.4, 4.5, 12.2, 12.3, 12.4, 13.3_

- [ ] 10. Checkpoint - Verify core UI and simulation flow
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 11. Implement XAI explanation and chart components
  - [ ] 11.1 Create ExplanationText component
    - Accept explanation string prop
    - Render section header "Fraud Detection Explanation"
    - Display explanation text with readable font and spacing
    - Use gray-300 color for text on dark background
    - Display placeholder "No data available" when explanation is null
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_
  
  - [ ]* 11.2 Write property test for explanation text rendering
    - **Property 6: Explanation Text Rendering** - Complete explanation rendered for any non-null string
    - Use fast-check with 100+ iterations
    - _Validates: Requirements 7.2_
  
  - [ ] 11.3 Create SHAPChart component
    - Accept features array prop (SHAPFeature[])
    - Sort features by importance in descending order (highest at top)
    - Render horizontal bar chart using Recharts
    - Display feature names on y-axis with 150px width
    - Display importance values on x-axis (0-100 range after percentage conversion)
    - Apply color gradient based on importance magnitude (darker for higher values)
    - Format tooltip values as percentages
    - Make chart responsive to viewport width using ResponsiveContainer
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 10.5_
  
  - [ ]* 11.4 Write property tests for SHAP chart data display
    - **Property 7: Feature Names Display** - All feature names displayed on y-axis
    - **Property 8: Feature Importance Sorting** - Features sorted descending by importance
    - Use fast-check with 100+ iterations per property
    - _Validates: Requirements 8.2, 8.4_
  
  - [ ]* 11.5 Write unit tests for SHAPChart component
    - Test chart renders with recharts components
    - Test all features appear in chart
    - Test features are sorted correctly
    - Test tooltip formatting
    - Test responsive container dimensions
    - _Requirements: 8.1-8.7, 10.5_

- [ ] 12. Implement XAIPanel component
  - [ ] 12.1 Create XAIPanel component
    - Accept explanation and shapFeatures props
    - Implement two-column layout on desktop (≥768px), stacked on mobile
    - Render ExplanationText component with explanation prop
    - Render SHAPChart component with shapFeatures prop
    - Display placeholder when data is null
    - Apply section headers "Fraud Detection Explanation" and "Feature Importance Analysis"
    - _Requirements: 7.1-7.5, 8.1-8.7, 10.5_
  
  - [ ]* 12.2 Write unit tests for XAIPanel
    - Test XAIPanel renders both ExplanationText and SHAPChart
    - Test section headers displayed
    - Test placeholder shown when data is null
    - Test responsive layout changes
    - _Requirements: 7.1-7.5, 8.1-8.7_

- [ ] 13. Implement state management and integration
  - [ ] 13.1 Create useFraudSimulation custom hook
    - Manage isLoading state
    - Manage results state (FraudDetectionResponse | null)
    - Provide simulateTransaction function that calls mockFraudService
    - Handle loading state transitions (set loading true, call service, set loading false, update results)
    - Add error handling for service failures
    - Return isLoading, results, simulateTransaction, and error
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 12.1, 12.4, 12.5_
  
  - [ ] 13.2 Wire DashboardLayout with state management
    - Use useFraudSimulation hook in DashboardLayout
    - Pass onSimulate callback to TransactionSimulator
    - Pass isLoading and results to EvaluationPanel
    - Pass explanation and shapFeatures from results to XAIPanel
    - Implement form submission flow: validation → simulation → results display
    - _Requirements: All requirements - integration of all components_
  
  - [ ]* 13.3 Write integration tests for complete flow
    - Test user enters valid transaction details, clicks simulate, sees loading, views results
    - Test form validation flow: invalid input → error → correction → error clears
    - Test loading state: button disabled during simulation, re-enabled after
    - Test results update: loading spinner → results display → XAI panel update
    - _Requirements: 2.1-2.7, 3.1-3.4, 11.1-11.5, 12.1-12.5_

- [ ] 14. Implement responsive design enhancements
  - [ ] 14.1 Add responsive breakpoints and mobile styles
    - Implement Tailwind responsive classes for all components
    - Desktop (≥1024px): side-by-side panels
    - Tablet (768-1023px): stacked panels with adjusted spacing
    - Mobile (<768px): stacked panels with mobile font sizes and spacing
    - Adjust header font sizes for mobile (reduce from 4xl to 2xl on small screens)
    - Ensure chart dimensions adjust based on viewport width
    - _Requirements: 10.1, 10.2, 10.3, 10.5_
  
  - [ ]* 14.2 Write property tests for responsive design
    - **Property 13: Cross-Viewport Functionality** - All functionality works from 320px to 2560px
    - **Property 14: Chart Responsiveness** - Chart adjusts dimensions without overflow
    - Use fast-check with viewport widths from 320px to 2560px
    - _Validates: Requirements 10.4, 10.5_
  
  - [ ]* 14.3 Write unit tests for responsive layouts
    - Test side-by-side layout at 1024px and above
    - Test stacked layout below 1024px
    - Test mobile font sizes applied below 768px
    - Test chart responsiveness at different viewport widths
    - _Requirements: 10.1, 10.2, 10.3, 10.5_

- [ ] 15. Checkpoint - Verify responsive design and integration
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 16. Implement accessibility features
  - [ ] 16.1 Add ARIA labels and accessibility attributes
    - Add aria-label to all form inputs
    - Add aria-live="polite" to EvaluationPanel for dynamic updates
    - Add descriptive alt text or aria-labels for visual indicators (badges, gauges)
    - Add aria-describedby for error messages linked to inputs
    - Add role attributes where appropriate (e.g., role="alert" for errors)
    - _Requirements: 13.2, 13.3, 13.5_
  
  - [ ] 16.2 Implement keyboard navigation support
    - Ensure all interactive elements are focusable with Tab key
    - Add focus styles for keyboard navigation (focus:ring utilities)
    - Support Enter key on form submission
    - Test tab order is logical (top to bottom, left to right)
    - _Requirements: 13.1_
  
  - [ ] 16.3 Ensure color contrast compliance
    - Verify all text elements meet 4.5:1 contrast ratio for WCAG AA
    - Use Tailwind colors that meet contrast requirements
    - Test with browser accessibility tools (axe DevTools)
    - _Requirements: 13.4_
  
  - [ ]* 16.4 Write property tests for accessibility
    - **Property 15: Accessibility Labels** - All interactive elements have aria-label or alt text
    - **Property 16: Color Contrast Compliance** - All text meets 4.5:1 contrast ratio
    - Use fast-check with 100+ iterations
    - Use @axe-core/react for automated accessibility testing
    - _Validates: Requirements 13.2, 13.4, 13.5_
  
  - [ ]* 16.5 Write unit tests for accessibility features
    - Test keyboard navigation through form fields
    - Test aria-live region on evaluation panel
    - Test disabled button tooltip
    - Test focus styles visible
    - _Requirements: 13.1, 13.2, 13.3, 13.5_

- [ ] 17. Implement error handling and boundaries
  - [ ] 17.1 Create ErrorBoundary component
    - Implement React error boundary class component
    - Catch rendering errors in componentDidCatch
    - Display user-friendly error message instead of blank screen
    - Log errors to console for debugging
    - Preserve rest of application functionality
    - _Requirements: Error handling best practices_
  
  - [ ] 17.2 Add error handling for mock service
    - Add try-catch in useFraudSimulation hook
    - Handle timeout scenarios (5 second timeout)
    - Display error message in EvaluationPanel when service fails
    - Allow user to retry after error
    - Log errors for debugging
    - _Requirements: 3.1, 3.2, 3.3, 3.4_
  
  - [ ] 17.3 Add response validation
    - Implement validateResponse function to check mock service response structure
    - Validate transaction_id is string
    - Validate status is "BLOCKED" or "APPROVED"
    - Validate fraud_probability is number between 0 and 1
    - Validate execution_time_ms is positive number
    - Throw error if response is invalid
    - _Requirements: 3.3, 3.4_
  
  - [ ]* 17.4 Write unit tests for error handling
    - Test ErrorBoundary catches and displays error
    - Test service timeout handling
    - Test invalid response handling
    - Test error message display in UI
    - Test retry functionality
    - _Requirements: Error handling_

- [ ] 18. Implement App component and wire everything together
  - [ ] 18.1 Create App component
    - Import and render Header component
    - Import and render DashboardLayout component
    - Wrap XAIPanel in ErrorBoundary for chart error handling
    - Apply global dark-mode background to body
    - Set up React 18 root rendering in main.tsx
    - _Requirements: All requirements - final integration_
  
  - [ ] 18.2 Configure Tailwind and global styles
    - Set up Tailwind configuration with custom theme colors (cyber-dark, cyber-blue, etc.)
    - Configure PostCSS with autoprefixer
    - Add custom fonts (Inter, Fira Code) to theme
    - Add custom box-shadow utilities for neon effects
    - Apply global styles in index.css
    - _Requirements: 1.5, 9.2_
  
  - [ ]* 18.3 Write end-to-end integration tests
    - Test complete fraud detection flow from form input to results display
    - Test form validation flow with error correction
    - Test loading states throughout the application
    - Test responsive behavior across breakpoints
    - Test accessibility features work end-to-end
    - _Requirements: All requirements_

- [ ] 19. Documentation and final polish
  - [ ] 19.1 Create comprehensive README.md
    - Add project overview and features
    - Add prerequisites (Node.js 16+)
    - Add installation instructions (`npm install`)
    - Add development server instructions (`npm run dev`)
    - Add build instructions (`npm run build`)
    - Add testing instructions (`npm test`, `npm run test:property`)
    - Add project structure explanation
    - Add technology stack details
    - Add future backend integration notes
    - _Requirements: 9.5_
  
  - [ ] 19.2 Add code documentation
    - Add JSDoc comments to all utility functions
    - Add prop type documentation with TypeScript interfaces
    - Add inline comments for complex logic
    - Document custom hooks with usage examples
    - _Requirements: Code maintainability_
  
  - [ ] 19.3 Performance optimization
    - Add lazy loading for XAIPanel component using React.lazy
    - Add useMemo for sortFeaturesByImportance function
    - Add useCallback for event handlers to prevent unnecessary re-renders
    - Optimize chart rendering performance
    - _Requirements: Performance best practices_

- [ ] 20. Final checkpoint - Complete testing and verification
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional testing sub-tasks and can be skipped for faster MVP iteration
- Each task references specific requirements from the requirements document for traceability
- The implementation uses **React 18 with TypeScript** as specified in the design document
- Property-based tests use **fast-check** library with minimum 100 iterations per property
- All 16 correctness properties from the design document are covered by property test sub-tasks
- Checkpoints ensure incremental validation and provide opportunities for user feedback
- The design includes comprehensive XAI visualizations with SHAP feature importance charts
- Accessibility compliance (WCAG AA) is built in from the start, not added later
- Error handling and loading states are first-class concerns throughout the implementation
- The mock service enables frontend development independent of backend with realistic 50ms latency simulation

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "2.2"] },
    { "id": 2, "tasks": ["3.1", "3.3", "3.5"] },
    { "id": 3, "tasks": ["3.2", "3.4", "3.6", "4.1", "4.2"] },
    { "id": 4, "tasks": ["4.3", "6.1", "6.2"] },
    { "id": 5, "tasks": ["6.3", "7.1", "7.2"] },
    { "id": 6, "tasks": ["6.4", "7.3", "8.1", "8.2"] },
    { "id": 7, "tasks": ["8.3", "9.1"] },
    { "id": 8, "tasks": ["9.2", "11.1"] },
    { "id": 9, "tasks": ["11.2", "11.3"] },
    { "id": 10, "tasks": ["11.4", "11.5", "12.1"] },
    { "id": 11, "tasks": ["12.2", "13.1"] },
    { "id": 12, "tasks": ["13.2"] },
    { "id": 13, "tasks": ["13.3", "14.1"] },
    { "id": 14, "tasks": ["14.2", "14.3", "16.1", "16.2", "16.3"] },
    { "id": 15, "tasks": ["16.4", "16.5", "17.1", "17.2", "17.3"] },
    { "id": 16, "tasks": ["17.4", "18.1", "18.2"] },
    { "id": 17, "tasks": ["18.3", "19.1", "19.2", "19.3"] }
  ]
}
```
