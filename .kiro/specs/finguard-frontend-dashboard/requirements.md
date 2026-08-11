# Requirements Document

## Introduction

The FinGuard Frontend Dashboard is a standalone, modern web application that provides a real-time interface for simulating and visualizing UPI fraud detection results. The dashboard enables users to input transaction details, evaluate fraud risk using a simulated backend, and understand fraud decisions through explainable AI visualizations. This frontend serves as a demonstration and prototype interface while the Spring Boot backend is under development.

## Glossary

- **Dashboard**: The web application interface for FinGuard fraud detection
- **Transaction_Simulator**: The UI component that accepts user input for transaction simulation
- **Evaluation_Panel**: The UI component that displays fraud detection results
- **XAI_Panel**: The explainable AI component that visualizes SHAP feature importances and explanations
- **Mock_Service**: The simulated backend service using hardcoded JSON responses
- **VPA**: Virtual Payment Address (e.g., user@ybl, merchant@paytm)
- **SHAP**: SHapley Additive exPlanations, a method for explaining ML model predictions
- **Fraud_Probability**: A numeric value between 0 and 1 indicating likelihood of fraud
- **Risk_Gauge**: Visual component displaying fraud probability as a dial or progress bar
- **Latency_Metric**: Display of inference time in milliseconds

## Requirements

### Requirement 1: Dashboard Layout and Structure

**User Story:** As a fraud analyst, I want a clean, organized dashboard layout, so that I can efficiently simulate transactions and review fraud detection results.

#### Acceptance Criteria

1. THE Dashboard SHALL render a header containing the title "FinGuard" and subtitle "Real-Time UPI Fraud Detection Engine"
2. THE Dashboard SHALL display a Transaction_Simulator on the left side of the layout
3. THE Dashboard SHALL display an Evaluation_Panel on the right side of the layout
4. THE Dashboard SHALL display an XAI_Panel below the Transaction_Simulator and Evaluation_Panel
5. THE Dashboard SHALL apply a dark-mode theme with a modern, high-tech aesthetic
6. THE Dashboard SHALL be fully responsive across desktop, tablet, and mobile viewport sizes

### Requirement 2: Transaction Input Form

**User Story:** As a user, I want to input transaction details through a form, so that I can simulate fraud detection for specific UPI transactions.

#### Acceptance Criteria

1. THE Transaction_Simulator SHALL provide an input field for Sender VPA
2. THE Transaction_Simulator SHALL provide an input field for Receiver VPA
3. THE Transaction_Simulator SHALL provide an input field for Amount in INR
4. THE Transaction_Simulator SHALL provide a "Simulate Transaction" button
5. WHEN any input field is empty, THE Transaction_Simulator SHALL disable the "Simulate Transaction" button
6. WHEN all input fields contain valid data, THE Transaction_Simulator SHALL enable the "Simulate Transaction" button
7. THE Transaction_Simulator SHALL display placeholder text for each input field with example values

### Requirement 3: Fraud Detection Simulation

**User Story:** As a user, I want the system to simulate a fraud detection API call, so that I can see realistic results without requiring a backend.

#### Acceptance Criteria

1. WHEN the "Simulate Transaction" button is clicked, THE Mock_Service SHALL display a loading spinner in the Evaluation_Panel
2. WHEN the loading spinner is displayed, THE Mock_Service SHALL wait 50 milliseconds to simulate API latency
3. WHEN the simulated delay completes, THE Mock_Service SHALL return the following hardcoded JSON response:
   ```json
   {
     "transaction_id": "tx-987654321",
     "status": "BLOCKED",
     "fraud_probability": 0.92,
     "execution_time_ms": 42,
     "xai_explanation": "Transaction blocked due to unusually high velocity of transfers to a newly created VPA combined with an anomalous time-of-day.",
     "shap_features": [
       { "feature": "Receiver VPA Age", "importance": 0.45 },
       { "feature": "Time Since Last Txn", "importance": 0.30 },
       { "feature": "Transaction Amount", "importance": 0.17 },
       { "feature": "Location Delta", "importance": 0.08 }
     ]
   }
   ```
4. WHEN the Mock_Service returns a response, THE Evaluation_Panel SHALL update to display the fraud detection results

### Requirement 4: Fraud Status Visualization

**User Story:** As a fraud analyst, I want to immediately see whether a transaction was blocked or approved, so that I can quickly assess the fraud detection outcome.

#### Acceptance Criteria

1. WHEN a transaction status is "BLOCKED", THE Evaluation_Panel SHALL display a red status badge with text "TRANSACTION BLOCKED"
2. WHEN a transaction status is "APPROVED", THE Evaluation_Panel SHALL display a green status badge with text "APPROVED"
3. THE Evaluation_Panel SHALL display the status badge prominently at the top of the results section
4. THE Evaluation_Panel SHALL display the status badge with high visibility and contrast
5. WHEN no simulation has been run, THE Evaluation_Panel SHALL display placeholder text indicating awaiting input

### Requirement 5: Risk Probability Gauge

**User Story:** As a fraud analyst, I want to see the fraud probability as a visual gauge, so that I can quickly assess the risk level of a transaction.

#### Acceptance Criteria

1. THE Risk_Gauge SHALL display the fraud probability as a percentage value
2. THE Risk_Gauge SHALL render as a visual dial or progress bar
3. WHEN fraud probability is above 0.70, THE Risk_Gauge SHALL display in red color
4. WHEN fraud probability is between 0.40 and 0.70, THE Risk_Gauge SHALL display in yellow color
5. WHEN fraud probability is below 0.40, THE Risk_Gauge SHALL display in green color
6. THE Risk_Gauge SHALL animate from 0 to the target percentage when results are displayed

### Requirement 6: Latency Metric Display

**User Story:** As a system administrator, I want to see the inference time for each fraud detection, so that I can verify the system meets real-time performance requirements.

#### Acceptance Criteria

1. THE Latency_Metric SHALL display the execution time in milliseconds
2. THE Latency_Metric SHALL render as a small badge near the Risk_Gauge
3. THE Latency_Metric SHALL format the display as "Inference Time: Xms" where X is the execution time value
4. WHEN execution time is below 100ms, THE Latency_Metric SHALL display in green color
5. WHEN execution time is 100ms or above, THE Latency_Metric SHALL display in yellow color

### Requirement 7: Explainable AI Text Explanation

**User Story:** As a fraud analyst, I want to read a human-readable explanation of why a transaction was flagged, so that I can understand the reasoning behind the fraud detection decision.

#### Acceptance Criteria

1. THE XAI_Panel SHALL display a text explanation section
2. THE XAI_Panel SHALL render the explanation text from the xai_explanation field in the mock response
3. THE XAI_Panel SHALL format the explanation text in a readable font with appropriate spacing
4. THE XAI_Panel SHALL display a section header "Fraud Detection Explanation" above the explanation text
5. WHEN no simulation has been run, THE XAI_Panel SHALL display placeholder text indicating no data available

### Requirement 8: SHAP Feature Importance Visualization

**User Story:** As a fraud analyst, I want to see which features contributed most to the fraud decision, so that I can understand the key risk factors in the transaction.

#### Acceptance Criteria

1. THE XAI_Panel SHALL render a horizontal bar chart displaying SHAP feature importances
2. THE XAI_Panel SHALL display feature names on the y-axis of the bar chart
3. THE XAI_Panel SHALL display importance values on the x-axis of the bar chart
4. THE XAI_Panel SHALL sort features by importance in descending order with highest importance at the top
5. THE XAI_Panel SHALL color-code bars based on importance magnitude with higher values in darker colors
6. THE XAI_Panel SHALL display a section header "Feature Importance Analysis" above the bar chart
7. THE XAI_Panel SHALL format importance values as percentages in the chart tooltips

### Requirement 9: Technology Stack and Dependencies

**User Story:** As a developer, I want the frontend to use modern, well-supported technologies, so that the codebase is maintainable and performant.

#### Acceptance Criteria

1. THE Dashboard SHALL be built using React.js with Vite as the build tool
2. THE Dashboard SHALL use Tailwind CSS for all styling and layout
3. THE Dashboard SHALL use Recharts or Chart.js for data visualization components
4. THE Dashboard SHALL include all necessary dependencies in a package.json file
5. THE Dashboard SHALL include a README with setup and run instructions
6. THE Dashboard SHALL require Node.js version 16 or higher

### Requirement 10: Responsive Design

**User Story:** As a user on various devices, I want the dashboard to adapt to my screen size, so that I can use the application on desktop, tablet, or mobile devices.

#### Acceptance Criteria

1. WHEN viewport width is 1024px or greater, THE Dashboard SHALL display Transaction_Simulator and Evaluation_Panel side-by-side
2. WHEN viewport width is below 1024px, THE Dashboard SHALL stack Transaction_Simulator above Evaluation_Panel
3. WHEN viewport width is below 768px, THE Dashboard SHALL adjust font sizes and spacing for mobile readability
4. THE Dashboard SHALL maintain all functionality across all responsive breakpoints
5. THE XAI_Panel SHALL adjust chart dimensions based on viewport width

### Requirement 11: Form Validation and User Feedback

**User Story:** As a user, I want clear feedback when I enter invalid data, so that I can correct my inputs and successfully simulate transactions.

#### Acceptance Criteria

1. WHEN a VPA input does not contain an "@" symbol, THE Transaction_Simulator SHALL display a validation error message below the input field
2. WHEN the Amount input is not a positive number, THE Transaction_Simulator SHALL display a validation error message below the input field
3. THE Transaction_Simulator SHALL clear all validation errors when the user corrects the input
4. THE Transaction_Simulator SHALL prevent form submission when validation errors exist
5. WHEN the "Simulate Transaction" button is disabled, THE Transaction_Simulator SHALL display a tooltip explaining why

### Requirement 12: Loading State Management

**User Story:** As a user, I want to see a loading indicator during simulation, so that I know the system is processing my request.

#### Acceptance Criteria

1. WHEN a simulation is in progress, THE Dashboard SHALL disable the "Simulate Transaction" button
2. WHEN a simulation is in progress, THE Evaluation_Panel SHALL display a centered loading spinner
3. WHEN a simulation is in progress, THE Evaluation_Panel SHALL hide previous results if they exist
4. WHEN a simulation completes, THE Dashboard SHALL re-enable the "Simulate Transaction" button
5. WHEN a simulation completes, THE Evaluation_Panel SHALL hide the loading spinner and display new results

### Requirement 13: Accessibility

**User Story:** As a user with accessibility needs, I want the dashboard to be keyboard-navigable and screen-reader friendly, so that I can use the application effectively.

#### Acceptance Criteria

1. THE Dashboard SHALL support full keyboard navigation through all interactive elements
2. THE Dashboard SHALL provide ARIA labels for all form inputs
3. THE Dashboard SHALL provide ARIA live regions for dynamic content updates in the Evaluation_Panel
4. THE Dashboard SHALL maintain color contrast ratios of at least 4.5:1 for all text elements
5. THE Dashboard SHALL provide descriptive alt text or ARIA labels for all visual indicators

