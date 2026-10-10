# OpenGTM Final Email Automation Workflow

This guide walks you through the complete end-to-end GTM automation pipeline:
**Discover → Research → Qualify → Message → Email Send**

## Prerequisites

1. **Install opengtm**:
```bash
cd ~/your-project-directory
git clone https://github.com/sharmasumitkumarsharma46-hue/opengtm-saas.git
cd opengtm-saas
pip install -e .
```

2. **Create `.env` file** (copy from `.env.example`):
```bash
cp .env.example .env
```

3. **Fill in your credentials** in `.env`:
```bash
# Gemini API key (required for lead discovery)
GEMINI_API_KEY=your_gemini_api_key_here

# SMTP settings (required for email sending)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your_email@gmail.com
SMTP_PASSWORD=your_app_password_here
SMTP_FROM=your_email@gmail.com
SMTP_USE_TLS=true
SMTP_USE_SSL=false
SMTP_TIMEOUT=30
```

**Note for Gmail users**: If you have 2FA enabled, generate an App Password:
1. Go to https://myaccount.google.com/apppasswords
2. Select "Mail" and "Windows Computer" (or your device)
3. Copy the 16-character password
4. Use that as `SMTP_PASSWORD` in `.env`

## Complete Workflow

### Step 1: Discover Companies
Find companies by industry + region:

```bash
opengtm discover \
  --industry "B2B SaaS" \
  --region "Berlin" \
  --limit 20 \
  --output /tmp/step1-discovered.json
```

Output: `/tmp/step1-discovered.json` with 20 companies

---

### Step 2: Research Companies
Extract contact info + run website audit:

```bash
opengtm research \
  --input /tmp/step1-discovered.json \
  --output /tmp/step2-researched.json
```

Output: `/tmp/step2-researched.json` with:
- Contact name + email
- LinkedIn URL
- Website audit findings
- Company context

---

### Step 3: Score ICP Fit
Rate leads 0-100 on your ideal customer profile:

```bash
opengtm qualify \
  --input /tmp/step2-researched.json \
  --icp-profile saas \
  --output /tmp/step3-qualified.json
```

Output: `/tmp/step3-qualified.json` with:
- ICP score (0-100)
- Tier: hot / warm / cold
- Qualification reason

---

### Step 4: Generate Messages
Create personalized outreach messages (LinkedIn + email):

```bash
opengtm message \
  --input /tmp/step3-qualified.json \
  --language en \
  --region "Berlin" \
  --output /tmp/step4-messages.json
```

Output: `/tmp/step4-messages.json` with:
- LinkedIn connection note
- LinkedIn first DM
- Email subject + body
- Message pattern (A/B/C/D/E)

---

### Step 5: Send Emails (DRY RUN)
Test email sending without actually sending:

```bash
# Create email template
cat > /tmp/email-template.txt << 'EOF'
Hi {first_name},

I noticed {company} is working in {industry}. 

I thought there might be a quick opportunity to help with your GTM motion – specifically around lead qualification and ICP scoring.

I'd love to share a quick idea if it's useful.

Best,
{sender_name}
EOF

# Send with --dry-run (no emails actually sent)
opengtm email \
  --input /tmp/step4-messages.json \
  --subject "Quick GTM idea for {company}" \
  --template /tmp/email-template.txt \
  --dry-run \
  --delay 0.5 \
  --output /tmp/step5-email-results-dryrun.json
```

Output: `/tmp/step5-email-results-dryrun.json` with:
- Preview of what would be sent
- Status: dry_run
- Subject + recipient for each lead

---

### Step 6: Send Emails (REAL)
Actually send emails (after reviewing dry run):

```bash
opengtm email \
  --input /tmp/step4-messages.json \
  --subject "Quick GTM idea for {company}" \
  --template /tmp/email-template.txt \
  --delay 0.5 \
  --output /tmp/step5-email-results.json
```

Output: `/tmp/step5-email-results.json` with:
- Status: sent / failed / skipped
- Email address
- Company name
- Delivery report

---

## Full Automated Pipeline (One Command)

Or run the entire pipeline end-to-end:

```bash
opengtm pipeline \
  --industry "B2B SaaS" \
  --region "Berlin" \
  --limit 10 \
  --icp-profile saas \
  --language en \
  --output /tmp/full-pipeline-results.json
```

This does:
1. Discover 10 companies
2. Research each one
3. Score ICP fit
4. Generate messages
5. Save to `/tmp/full-pipeline-results.json`

Then send emails:
```bash
opengtm email \
  --input /tmp/full-pipeline-results.json \
  --subject "Quick GTM idea for {company}" \
  --template /tmp/email-template.txt \
  --dry-run
```

---

## Email Template Variables

Use these placeholders in your template:

- `{first_name}` - Contact's first name
- `{company}` - Company name
- `{industry}` - Company's industry
- `{domain}` - Company website domain
- `{sender_name}` - Your email address (from SMTP_FROM)

Example template:

```text
Hi {first_name},

I saw {company} is in {industry} and thought you might benefit from [your value prop].

[Your specific insight about their domain/industry]

Would you be open to a quick 15-min chat?

Best,
{sender_name}
```

---

## Email Sending Options

```bash
opengtm email \
  --input leads.json \
  --subject "Subject template with {placeholders}" \
  --template email-template.txt \
  --dry-run \                    # Test without sending (optional)
  --delay 0.5 \                  # Seconds between emails (optional)
  --output results.json          # Save delivery report
```

---

## Monitoring & Results

After each step, check the JSON output:

```bash
# View discovered companies
cat /tmp/step1-discovered.json | jq '.[] | {company, domain}' | head -5

# View qualified leads
cat /tmp/step3-qualified.json | jq '.[] | {company, tier: .qualification.tier, score: .qualification.score}' | head -5

# View email results
cat /tmp/step5-email-results.json | jq '.results[] | {company, status, email}'
```

---

## Troubleshooting

### Error: "SMTP_HOST is not set"
- Make sure `.env` file exists
- Make sure you have SMTP credentials filled in
- Test with: `echo $SMTP_HOST`

### Error: "SMTP authentication failed"
- Check SMTP_USERNAME and SMTP_PASSWORD are correct
- For Gmail, make sure you're using App Password (not regular password)
- For Outlook, try SMTP_HOST=smtp.office365.com

### Error: "Lead missing email address"
- Make sure leads have `email`, `contact_email`, or `email_address` field
- Check that research step extracted contact emails

### Emails not sending in production?
- Always test with `--dry-run` first
- Check email logs: `tail -f /tmp/opengtm-email-results.json`
- Add `--delay 1.0` to space out sends (avoid rate limiting)

---

## Advanced Workflow

### Filter by ICP Tier

Send emails only to "hot" leads:

```bash
# Extract hot leads only
cat /tmp/step3-qualified.json | jq '[.[] | select(.qualification.tier == "hot")]' > /tmp/hot-leads.json

# Send emails only to hot leads
opengtm email \
  --input /tmp/hot-leads.json \
  --subject "Exclusive opportunity for {company}" \
  --template /tmp/email-template.txt \
  --dry-run
```

### A/B Test Email Templates

Create two templates:

```bash
cat > /tmp/template-a.txt << 'EOF'
Hi {first_name},

[Template A message]
EOF

cat > /tmp/template-b.txt << 'EOF'
Hi {first_name},

[Template B message]
EOF

# Send A to first half
head -n 5 /tmp/step4-messages.json > /tmp/leads-a.json
opengtm email --input /tmp/leads-a.json --subject "..." --template /tmp/template-a.txt

# Send B to second half
tail -n 5 /tmp/step4-messages.json > /tmp/leads-b.json
opengtm email --input /tmp/leads-b.json --subject "..." --template /tmp/template-b.txt
```

### Schedule Multiple Sends

Send in waves:

```bash
# First wave: hot leads, immediate
cat /tmp/step3-qualified.json | jq '[.[] | select(.qualification.tier == "hot")]' > /tmp/wave1.json
opengtm email --input /tmp/wave1.json --subject "Quick GTM idea for {company}" --template email-template.txt

# Second wave: warm leads, next day
cat /tmp/step3-qualified.json | jq '[.[] | select(.qualification.tier == "warm")]' > /tmp/wave2.json
# Run this command tomorrow

# Third wave: cold leads, week later
cat /tmp/step3-qualified.json | jq '[.[] | select(.qualification.tier == "cold")]' > /tmp/wave3.json
# Run this command next week
```

---

## Summary

**Full workflow in 6 steps:**

```bash
# 1. Discover
opengtm discover --industry "B2B SaaS" --region "Berlin" --limit 20 -o /tmp/1-discovered.json

# 2. Research
opengtm research --input /tmp/1-discovered.json -o /tmp/2-researched.json

# 3. Qualify
opengtm qualify --input /tmp/2-researched.json --icp-profile saas -o /tmp/3-qualified.json

# 4. Message
opengtm message --input /tmp/3-qualified.json -o /tmp/4-messages.json

# 5. Dry Run
opengtm email --input /tmp/4-messages.json --subject "Quick idea for {company}" --template email-template.txt --dry-run -o /tmp/5-dryrun.json

# 6. Send
opengtm email --input /tmp/4-messages.json --subject "Quick idea for {company}" --template email-template.txt -o /tmp/5-results.json
```

All done! You now have:
- 20 discovered companies
- Researched with contact info
- Scored on ICP fit
- Personalized emails generated
- Emails sent

Entire pipeline takes ~30-45 minutes depending on company count.

---

**Questions?** Check the repo:
- https://github.com/sharmasumitkumarsharma46-hue/opengtm-saas
