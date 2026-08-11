# FinGuard Frontend Dashboard

A modern, responsive React-based web application for simulating and visualizing UPI fraud detection with explainable AI.

## 🚀 Technology Stack

- **React 19.x** - Modern UI library with hooks
- **TypeScript 6.x** - Type-safe development
- **Vite 8.x** - Lightning-fast build tool and dev server
- **Tailwind CSS 4.x** - Utility-first CSS framework with cyber-themed dark mode
- **Vitest** - Fast unit testing framework
- **React Testing Library** - Component testing utilities
- **fast-check** - Property-based testing library
- **Recharts** - Declarative charting library for data visualization
- **Framer Motion** - Animation library for smooth UI transitions
- **@axe-core/react** - Accessibility testing integration
- **Oxlint** - Fast JavaScript/TypeScript linter
- **Prettier** - Code formatter

## 📁 Project Structure

```
finguard-dashboard/
├── src/
│   ├── components/       # React components
│   ├── services/         # API and mock services
│   │   └── mockFraudService.ts
│   ├── types/            # TypeScript type definitions
│   │   └── index.ts
│   ├── utils/            # Utility functions
│   │   ├── validation.ts
│   │   └── validation.test.ts
│   ├── hooks/            # Custom React hooks
│   ├── test/             # Test setup and utilities
│   │   └── setup.ts
│   ├── App.tsx           # Main application component
│   ├── main.tsx          # Application entry point
│   └── index.css         # Global styles with Tailwind
├── public/               # Static assets
├── dist/                 # Production build output
├── tailwind.config.js    # Tailwind CSS configuration
├── postcss.config.js     # PostCSS configuration
├── vite.config.ts        # Vite and Vitest configuration
├── tsconfig.json         # TypeScript configuration
└── package.json          # Project dependencies and scripts
```

## 🛠️ Prerequisites

- **Node.js** version 16.x or higher
- **npm** (comes with Node.js)

## 📦 Installation

1. Clone or navigate to the project directory:
   ```bash
   cd finguard-dashboard
   ```

2. Install dependencies:
   ```bash
   npm install
   ```

## 🎯 Available Scripts

### Development
```bash
npm run dev
```
Starts the development server with Hot Module Replacement (HMR) at `http://localhost:5173`

### Build
```bash
npm run build
```
Creates an optimized production build in the `dist/` directory

### Preview
```bash
npm run preview
```
Preview the production build locally

### Testing
```bash
npm run test           # Run tests in watch mode
npm run test:run       # Run tests once
npm run test:ui        # Run tests with UI interface
npm run test:coverage  # Run tests with coverage report
```

### Linting
```bash
npm run lint
```
Run Oxlint to check code quality

### Formatting
```bash
npm run format
```
Format code using Prettier

## 🎨 Tailwind CSS Configuration

The project uses Tailwind CSS v4 with a custom cyber-themed dark mode palette:

- **cyber-dark**: `#0a0e27`
- **cyber-darker**: `#060913`
- **cyber-blue**: `#00d9ff`
- **cyber-purple**: `#b026ff`
- **cyber-pink**: `#ff006e`
- **cyber-green**: `#00ff88`

## 🧪 Testing Strategy

The project employs a dual testing approach:

1. **Unit Tests**: Example-based tests for specific scenarios using Vitest and React Testing Library
2. **Property-Based Tests**: Using fast-check to test universal behaviors across many inputs

Tests are located alongside their source files with a `.test.ts` or `.test.tsx` extension.

## 📐 TypeScript Configuration

TypeScript is configured with **strict mode** enabled for maximum type safety:
- `strict: true`
- `strictNullChecks: true`
- `strictFunctionTypes: true`
- All strict type checking options enabled

## 🔧 Development Features

- ⚡ **Hot Module Replacement (HMR)** - Instant feedback during development
- 🎯 **Type Safety** - Full TypeScript coverage with strict mode
- 📱 **Responsive Design** - Mobile-first approach with Tailwind CSS
- ♿ **Accessibility** - WCAG 2.1 AA compliance with axe-core integration
- 🧪 **Comprehensive Testing** - Unit and property-based tests
- 🎨 **Code Quality** - Oxlint + Prettier for consistent code style

## 🚦 Getting Started

1. **Install dependencies:**
   ```bash
   npm install
   ```

2. **Start development server:**
   ```bash
   npm run dev
   ```

3. **Open browser:**
   Navigate to `http://localhost:5173`

4. **Run tests:**
   ```bash
   npm run test
   ```

## 📝 Mock Service

The application includes a mock fraud detection service (`mockFraudService.ts`) that simulates backend API calls with hardcoded responses. This enables frontend development independent of backend availability.

## 🎯 Requirements Validation

This project setup validates the following requirements:
- ✅ **9.1**: React.js with Vite build tool
- ✅ **9.2**: Tailwind CSS for styling
- ✅ **9.3**: Recharts for data visualization
- ✅ **9.4**: package.json with all dependencies
- ✅ **9.5**: README with setup instructions
- ✅ **9.6**: Node.js version 16 or higher

## 🔄 Next Steps

- Implement dashboard components (Header, TransactionSimulator, EvaluationPanel, XAIPanel)
- Create form validation logic
- Build visualization components (RiskGauge, SHAPChart)
- Implement responsive layouts
- Add accessibility features
- Write comprehensive tests

## 📄 License

This project is part of the FinGuard UPI Fraud Detection system.
