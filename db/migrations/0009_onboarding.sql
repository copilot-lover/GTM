-- Add onboarding tracking to workspaces
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS onboarding_completed boolean NOT NULL DEFAULT false;
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS onboarding_step text NOT NULL DEFAULT 'welcome';