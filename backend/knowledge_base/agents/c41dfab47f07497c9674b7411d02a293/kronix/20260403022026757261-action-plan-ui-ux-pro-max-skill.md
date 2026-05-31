# UI/UX Execution Plan - ui-ux-pro-max-skill

## Goal
Improve current UI with a practical, phased design-system rollout.

## Quick Wins
- Replace top 10 repeated hardcoded colors with semantic tokens
- Add focus ring utility class and apply to all buttons/links/inputs
- Standardize transition duration to 150-250ms for hover/focus states

## Phases
### P1 - Token Foundation
- Priority: high
- Effort: 1-2 days
- Impact: high

- [ ] Create semantic tokens for color, spacing, radius, typography
  - Where: C:\Users\Felipe\Desktop\ui-ux-pro-max-skill\src\styles\tokens.css
  - Done when: At least primary/secondary/background/text/success/danger + spacing scale exist as CSS variables
- [ ] Map hardcoded hex values to tokens in key UI components
  - Where: C:\Users\Felipe\Desktop\ui-ux-pro-max-skill\src\components
  - Done when: Top 20 UI files stop using raw hex colors directly

### P2 - Accessibility Hardening
- Priority: high
- Effort: 1 day
- Impact: high

- [ ] Add visible :focus / :focus-visible styles to all interactive components
  - Where: C:\Users\Felipe\Desktop\ui-ux-pro-max-skill\src\styles\tokens.css
  - Done when: Keyboard tab navigation always shows a visible ring
- [ ] Increase ARIA usage for buttons, dialogs, menus, and dynamic widgets
  - Where: C:\Users\Felipe\Desktop\ui-ux-pro-max-skill\src\components
  - Done when: Key interaction components include proper aria-* semantics

### P3 - Interaction Consistency
- Priority: medium
- Effort: 0.5-1 day
- Impact: medium

- [ ] Define motion tokens (duration/easing) and standard hover/focus transitions
  - Where: C:\Users\Felipe\Desktop\ui-ux-pro-max-skill\src\styles\tokens.css
  - Done when: Shared motion variables are used across interactive components
- [ ] Align Tailwind theme tokens (if applicable)
  - Where: C:\Users\Felipe\Desktop\ui-ux-pro-max-skill\tailwind.config.ts
  - Done when: Tailwind theme points to design token palette/spacing

### P4 - Recommended Visual Direction
- Priority: medium
- Effort: 1-2 days
- Impact: medium

- [ ] Apply recommended style direction from audit query 'saas web app trust'
  - Where: C:\Users\Felipe\Desktop\ui-ux-pro-max-skill\src\components
  - Done when: Hero, cards, buttons, forms, and nav follow the same visual language
- [ ] Persist rollout checklist for the team
  - Where: C:\Users\Felipe\Desktop\ui-ux-pro-max-skill\design-system\action-plan.md
  - Done when: Action plan markdown exists and is shared in project docs
