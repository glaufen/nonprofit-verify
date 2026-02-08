-- Add Stripe fields to api_keys table
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS stripe_customer_id VARCHAR(255);
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS stripe_subscription_id VARCHAR(255);
CREATE INDEX IF NOT EXISTS idx_api_keys_stripe_customer ON api_keys(stripe_customer_id) WHERE stripe_customer_id IS NOT NULL;
