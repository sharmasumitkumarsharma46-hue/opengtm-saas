"""
cli.py - Unified CLI entrypoint for opengtm.

Commands:
  opengtm discover  - Find companies by industry + region
  opengtm research  - Research a domain (contact + website audit)
  opengtm qualify   - Score ICP fit for a list of leads
  opengtm message   - Generate outreach messages from audit data
  opengtm email     - Send personalized outbound emails to leads
  opengtm pipeline  - Run full end-to-end pipeline
  opengtm outreach  - Show/manage outreach sequence queue
  opengtm sync      - Push leads to Google Sheet CRM
  opengtm context   - Extract company context from a URL
  opengtm analytics - Run AEO health check (29 checks) + AI visibility
  opengtm blog      - Generate blog article with Gemini + Google Search
  opengtm keywords  - Research SEO keywords (7-stage pipeline)
  opengtm sitemap   - Crawl and classify sitemap URLs
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .outreach import DEFAULT_DAILY_LIMIT


def _load_dotenv():
    """Load .env file from current directory if present."""
    env_file = Path(".env")
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    if key.strip() not in os.environ:
                        os.environ[key.strip()] = val.strip().strip('"').strip("'")


def cmd_discover(args):
    from .discover import discover as _discover
    print(f"[discover] {args.industry} | {args.region} | limit {args.limit}", flush=True)
    results = _discover(
        industry=args.industry,
        region=args.region,
        limit=args.limit,
        validate=not args.no_validate,
        verbose=True,
    )
    with open(args.output, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n{len(results)} companies -> {args.output}", flush=True)


def cmd_research(args):
    from .research import research as _research
    import time

    if args.domain:
        result = _research(
            domain=args.domain,
            company=args.company or args.domain,
            industry=args.industry or "",
            verbose=True,
        )
        output = [{"domain": args.domain, "company": args.company or args.domain, "research": result}]
    elif args.input:
        with open(args.input) as f:
            leads = json.load(f)
        output = []
        for i, lead in enumerate(leads):
            print(f"\n[{i+1}/{len(leads)}] {lead.get('company', lead['domain'])}", flush=True)
            result = _research(
                domain=lead["domain"],
                company=lead.get("company", ""),
                industry=lead.get("industry", ""),
                verbose=True,
            )
            output.append({**lead, "audit": result})
            if i < len(leads) - 1:
                time.sleep(3)
    else:
        print("ERROR: provide --domain or --input", file=sys.stderr)
        sys.exit(1)

    with open(args.output, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\n{len(output)} researched -> {args.output}", flush=True)


def cmd_qualify(args):
    from .qualify import qualify_batch

    with open(args.input) as f:
        leads = json.load(f)

    print(f"[qualify] Scoring {len(leads)} leads (ICP profile: {args.icp_profile})", flush=True)
    results = qualify_batch(leads, icp_profile=args.icp_profile, verbose=True)

    with open(args.output, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    hot = sum(1 for r in results if r["qualification"]["tier"] == "hot")
    warm = sum(1 for r in results if r["qualification"]["tier"] == "warm")
    cold = sum(1 for r in results if r["qualification"]["tier"] == "cold")
    print(f"\nResults: {hot} hot, {warm} warm, {cold} cold -> {args.output}", flush=True)


def cmd_message(args):
    from .message import generate_messages

    with open(args.input) as f:
        leads = json.load(f)

    lang = args.language or os.environ.get("DEFAULT_LANGUAGE", "en")
    region = args.region or ""

    print(f"[message] Generating for {len(leads)} leads (language: {lang})", flush=True)
    results = []
    patterns = {}
    for lead in leads:
        audit = lead.get("audit") or lead.get("research") or {}
        if isinstance(audit, dict) and "research" in audit:
            audit = audit["research"]
        messages = generate_messages(
            domain=lead.get("domain", ""),
            company=lead.get("company", ""),
            contact_name=lead.get("contact_name", ""),
            industry=lead.get("industry", ""),
            audit=audit,
            region=region,
            contact_title=lead.get("contact_title", ""),
            language=lang,
        )
        results.append({**lead, "messages": messages})
        p = messages["pattern"]
        patterns[p] = patterns.get(p, 0) + 1
        print(f"  {lead.get('company', lead.get('domain', '?'))}: Pattern {p}", flush=True)

    with open(args.output, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nPatterns: {dict(sorted(patterns.items()))}", flush=True)
    print(f"{len(results)} messages -> {args.output}", flush=True)


def cmd_email(args):
    """Send personalized outbound emails to a list of leads."""
    from .emailer import EmailConfig, send_bulk_emails, load_template

    with open(args.input) as f:
        leads = json.load(f)

    body_template = load_template(args.template)
    config = EmailConfig.from_env()

    print(f"[email] Sending {len(leads)} emails (dry_run={args.dry_run})", flush=True)
    result = send_bulk_emails(
        leads=leads,
        subject_template=args.subject,
        body_template=body_template,
        config=config,
        dry_run=args.dry_run,
        verbose=True,
        delay_between_sends=args.delay,
    )

    with open(args.output, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"\nEmail results -> {args.output}", flush=True)


def cmd_pipeline(args):
    """Full end-to-end pipeline: discover -> research -> qualify -> message -> sync."""
    import time
    from .discover import discover as _discover
    from .research import research as _research
    from .qualify import qualify_batch
    from .message import generate_messages
    from .sync import sync_leads, build_sync_payload

    lang = args.language or os.environ.get("DEFAULT_LANGUAGE", "en")
    output_path = args.output or f"/tmp/opengtm-pipeline-{args.industry.replace(' ', '-').lower()}.json"

    print(f"{'='*60}", flush=True)
    print(f"PIPELINE: {args.industry} | {args.region} | limit {args.limit}", flush=True)
    print(f"{'='*60}", flush=True)

    print(f"\nSTEP 1: DISCOVER", flush=True)
    prospects = _discover(
        industry=args.industry,
        region=args.region,
        limit=args.limit,
        verbose=True,
    )
    if not prospects:
        print("No companies discovered. Exiting.", flush=True)
        sys.exit(1)

    print(f"\nSTEP 2: RESEARCH ({len(prospects)} companies)", flush=True)
    researched = []
    for i, p in enumerate(prospects):
        print(f"\n  [{i+1}/{len(prospects)}] {p['company']} ({p['domain']})", flush=True)
        audit = _research(
            domain=p["domain"],
            company=p["company"],
            industry=p["industry"],
            verbose=True,
        )
        contact = audit.get("contact", {})
        researched.append({
            **p,
            "contact_name": contact.get("name", ""),
            "contact_title": contact.get("title", ""),
            "contact_email": contact.get("email"),
            "linkedin_url": contact.get("linkedin_url"),
            "audit": audit,
        })
        if i < len(prospects) - 1:
            time.sleep(3)

    print(f"\nSTEP 3: QUALIFY", flush=True)
    qualified = qualify_batch(
        researched,
        icp_profile=args.icp_profile,
        verbose=True,
    )

    print(f"\nSTEP 4: GENERATE MESSAGES", flush=True)
    for lead in qualified:
        messages = generate_messages(
            domain=lead["domain"],
            company=lead["company"],
            contact_name=lead.get("contact_name", ""),
            industry=lead.get("industry", ""),
            audit=lead.get("audit"),
            region=args.region,
            contact_title=lead.get("contact_title", ""),
            language=lang,
        )
        lead["messages"] = messages
        print(f"  {lead['company']}: Pattern {messages['pattern']}", flush=True)

    with open(output_path, "w") as f:
        json.dump(qualified, f, indent=2, ensure_ascii=False)
    print(f"\nResults -> {output_path}", flush=True)

    if not args.no_sync and os.environ.get("CRM_WEBHOOK_URL"):
        print(f"\nSTEP 5: SYNC TO CRM", flush=True)
        sync_data = [build_sync_payload(lead) for lead in qualified]
        sync_leads(sync_data, dry_run=args.dry_run, verbose=True)
    elif args.no_sync:
        print(f"\nSTEP 5: SYNC SKIPPED (--no-sync)", flush=True)
    else:
        print(f"\nSTEP 5: SYNC SKIPPED (CRM_WEBHOOK_URL not set)", flush=True)

    hot = sum(1 for r in qualified if r["qualification"]["tier"] == "hot")
    warm = sum(1 for r in qualified if r["qualification"]["tier"] == "warm")
    cold = sum(1 for r in qualified if r["qualification"]["tier"] == "cold")
    print(f"\n{'='*60}", flush=True)
    print(f"PIPELINE COMPLETE", flush=True)
    print(f"  Discovered:  {len(prospects)}", flush=True)
    print(f"  Researched:  {len(researched)}", flush=True)
    print(f"  Qualified:   {hot} hot, {warm} warm, {cold} cold", flush=True)
    print(f"{'='*60}", flush=True)


def cmd_outreach(args):
    from .outreach import OutreachSequence

    if args.action == "status":
        if not args.state_file or not Path(args.state_file).exists():
            print("ERROR: --state-file required and must exist for status", file=sys.stderr)
            sys.exit(1)
        seq = OutreachSequence.load(args.state_file)
        stats = seq.get_stats()
        print(json.dumps(stats, indent=2))

    elif args.action == "queue":
        if not args.state_file or not Path(args.state_file).exists():
            print("ERROR: --state-file required and must exist for queue", file=sys.stderr)
            sys.exit(1)
        seq = OutreachSequence.load(args.state_file)
        seq.print_queue(touch=args.touch)

    elif args.action == "load":
        if not args.input:
            print("ERROR: --input required for load", file=sys.stderr)
            sys.exit(1)
        with open(args.input) as f:
            leads = json.load(f)
        state_path = args.state_file or "/tmp/opengtm-outreach-state.json"
        if Path(state_path).exists():
            seq = OutreachSequence.load(state_path, daily_limit=args.daily_limit)
        else:
            seq = OutreachSequence(daily_limit=args.daily_limit)
        added = seq.add_leads(leads)
        seq.export(state_path)
        print(f"Added {added} new leads to sequence -> {state_path}", flush=True)
        stats = seq.get_stats()
        print(f"Total: {stats['total_leads']} leads | {stats['due_today']} due today", flush=True)


def cmd_sync(args):
    from .sync import sync_leads, build_sync_payload

    with open(args.input) as f:
        leads = json.load(f)

    sync_data = [build_sync_payload(lead) for lead in leads if lead.get("messages", {}).get("pattern") != "SKIP"]
    skipped = len(leads) - len(sync_data)

    if skipped:
        print(f"[sync] Skipping {skipped} SKIP-pattern leads", flush=True)

    sync_leads(sync_data, dry_run=args.dry_run, verbose=True)


def cmd_context(args):
    """Extract company context from a URL."""
    from .context import extract_context

    print(f"[context] Extracting context for {args.url}", flush=True)

    user_context = None
    if args.country or args.language:
        user_context = {}
        if args.country:
            user_context["country"] = args.country
        if args.language:
            user_context["language"] = args.language

    result = extract_context(
        url=args.url,
        user_context=user_context,
        fallback_on_error=not args.strict,
    )

    output_path = args.output or "/tmp/opengtm-context.json"
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"Company: {result.get('company_name', 'Unknown')}", flush=True)
    print(f"Industry: {result.get('industry', '')}", flush=True)
    print(f"Products: {', '.join(result.get('products', [])[:3])}", flush=True)
    print(f"\nContext -> {output_path}", flush=True)


def cmd_analytics(args):
    """Run AEO health check and/or AI visibility check."""
    from .analytics import run_health_check, run_mentions

    if args.health_only or not args.company:
        if not args.url:
            print("ERROR: --url required for health check", file=sys.stderr)
            sys.exit(1)
        print(f"[analytics] Health check: {args.url}", flush=True)
        result = run_health_check(args.url)
        output_path = args.output or "/tmp/opengtm-analytics.json"
        with open(output_path, "w") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"Score: {result.get('score', 0)} | Grade: {result.get('grade', '?')}", flush=True)
        print(f"\nResults -> {output_path}", flush=True)

    elif args.mentions_only or not args.url:
        if not args.company:
            print("ERROR: --company required for mentions check", file=sys.stderr)
            sys.exit(1)
        print(f"[analytics] Mentions check: {args.company}", flush=True)
        result = run_mentions(
            domain=args.url or "",
            company_name=args.company,
            industry=args.industry or "",
        )
        output_path = args.output or "/tmp/opengtm-mentions.json"
        with open(output_path, "w") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"Visibility: {result.get('visibility_score', 0):.1f}% | Queries: {result.get('queries_tested', 0)}", flush=True)
        print(f"\nResults -> {output_path}", flush=True)

    else:
        print(f"[analytics] Full analysis: {args.url} | {args.company}", flush=True)
        health = run_health_check(args.url)
        mentions = run_mentions(
            domain=args.url,
            company_name=args.company,
            industry=args.industry or "",
        )
        result = {
            "url": args.url,
            "company": args.company,
            "health": health,
            "mentions": mentions,
        }
        output_path = args.output or "/tmp/opengtm-analytics.json"
        with open(output_path, "w") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"Health: {health.get('score', 0)} ({health.get('grade', '?')}) | Visibility: {mentions.get('visibility_score', 0):.1f}%", flush=True)
        print(f"\nResults -> {output_path}", flush=True)


def cmd_blog(args):
    """Generate a blog article."""
    from .blog import generate_article

    print(f"[blog] Generating article: '{args.keyword}' for {args.domain}", flush=True)

    context = None
    if args.context:
        with open(args.context) as f:
            context = json.load(f)

    result = generate_article(
        domain=args.domain,
        keyword=args.keyword,
        context=context,
        word_count=args.word_count,
        language=args.language,
        country=args.country,
        verify_urls=args.verify_urls,
    )

    output_path = args.output or "/tmp/opengtm-blog.json"
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"Title: {result.get('title', '')}", flush=True)
    print(f"Words: {result.get('word_count', 0)} | Sources: {len(result.get('sources', []))}", flush=True)
    if result.get("is_too_similar"):
        print(f"WARNING: High similarity {result['similarity_score']:.1%} - possible content cannibalization", flush=True)
    print(f"\nArticle -> {output_path}", flush=True)


def cmd_keywords(args):
    """Research SEO keywords."""
    from .keywords import research_keywords

    print(f"[keywords] Researching keywords for {args.domain} (limit: {args.limit})", flush=True)

    context = None
    if args.context:
        with open(args.context) as f:
            context = json.load(f)

    results = research_keywords(
        domain=args.domain,
        context=context,
        limit=args.limit,
        language=args.language,
        region=args.region,
        min_score=args.min_score,
        cluster_count=args.clusters,
        generate_briefs=not args.no_briefs,
    )

    output_path = args.output or "/tmp/opengtm-keywords.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n{len(results)} keywords found", flush=True)
    if results:
        top5 = results[:5]
        print(f"Top 5:", flush=True)
        for kw in top5:
            brief_flag = " [brief]" if kw.get("content_brief") else ""
            print(f"  [{kw.get('score', 0):3d}] {kw['keyword']} ({kw.get('cluster', '?')}){brief_flag}", flush=True)
    print(f"\nKeywords -> {output_path}", flush=True)


def cmd_sitemap(args):
    """Crawl and classify sitemap URLs."""
    from .sitemap import crawl_sitemap

    print(f"[sitemap] Crawling {args.url}", flush=True)

    result = crawl_sitemap(
        url=args.url,
        validate=args.validate,
        max_urls=args.max_urls,
    )

    output_path = args.output or "/tmp/opengtm-sitemap.json"
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"Total pages: {result['total_pages']}", flush=True)
    print(f"Blog: {len(result['blog_urls'])} | Product: {len(result['product_urls'])} | Service: {len(result['service_urls'])}", flush=True)
    print(f"Docs: {len(result['docs_urls'])} | Resource: {len(result['resource_urls'])} | Other: {len(result['other_urls'])}", flush=True)
    print(f"\nSitemap -> {output_path}", flush=True)


def main():
    _load_dotenv()

    parser = argparse.ArgumentParser(
        prog="opengtm",
        description="AI-powered GTM automation: discover leads, research, score ICP, generate outreach.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  opengtm discover --industry "B2B SaaS" --region "Berlin" --limit 20
  opengtm research --domain example.com --company "Acme" --industry "SaaS"
  opengtm qualify --input discovered.json --icp-profile saas
  opengtm message --input qualified.json --language en
  opengtm email --input qualified.json --subject "Quick idea for {company}" --template email-template.txt
  opengtm pipeline --industry "IT Services" --region "Hamburg" --limit 10
  opengtm outreach load --input qualified.json --state-file seq.json
  opengtm outreach queue --state-file seq.json
  opengtm sync --input generated.json --dry-run
  opengtm context --url https://example.com
  opengtm analytics --url https://example.com --company "Example Corp"
  opengtm blog --domain example.com --keyword "best practices for SaaS onboarding"
  opengtm keywords --domain example.com --limit 50
  opengtm sitemap --url https://example.com
        """,
    )
    sub = parser.add_subparsers(dest="command")

    p_disc = sub.add_parser("discover", help="Find companies via Gemini + Google Search")
    p_disc.add_argument("--industry", "-i", required=True, help="Industry (e.g. 'B2B SaaS', 'IT Services')")
    p_disc.add_argument("--region", "-r", required=True, help="City or region (e.g. 'Berlin', 'San Francisco')")
    p_disc.add_argument("--limit", "-n", type=int, default=20, help="Max companies to return (default 20)")
    p_disc.add_argument("--output", "-o", default="/tmp/opengtm-discovered.json")
    p_disc.add_argument("--no-validate", action="store_true", help="Skip URL reachability check")

    p_res = sub.add_parser("research", help="Research domains: extract contact + run website audit")
    p_res.add_argument("--domain", "-d", help="Single domain to research")
    p_res.add_argument("--company", "-c", help="Company name (with --domain)")
    p_res.add_argument("--industry", help="Industry (with --domain)")
    p_res.add_argument("--input", help="JSON file with leads [{domain, company, industry}]")
    p_res.add_argument("--output", "-o", default="/tmp/opengtm-researched.json")

    p_qual = sub.add_parser("qualify", help="Score leads on ICP fit (0-100)")
    p_qual.add_argument("--input", required=True, help="JSON file with researched leads")
    p_qual.add_argument("--icp-profile", default="default",
                        choices=["default", "saas", "agency", "professional_services"],
                        help="ICP profile to score against (default: default)")
    p_qual.add_argument("--output", "-o", default="/tmp/opengtm-qualified.json")

    p_msg = sub.add_parser("message", help="Generate outreach messages from audit findings")
    p_msg.add_argument("--input", required=True, help="JSON file with qualified leads")
    p_msg.add_argument("--language", choices=["en", "de"], help="Message language (default: en)")
    p_msg.add_argument("--region", help="Region for peer comparison messages")
    p_msg.add_argument("--output", "-o", default="/tmp/opengtm-messages.json")

    p_email = sub.add_parser("email", help="Send personalized outbound emails to leads")
    p_email.add_argument("--input", required=True, help="JSON file with leads")
    p_email.add_argument("--subject", required=True, help="Email subject template")
    p_email.add_argument("--template", help="Text file with the email body template")
    p_email.add_argument("--dry-run", action="store_true", help="Do not actually send emails")
    p_email.add_argument("--delay", type=float, default=0.0, help="Seconds between sends (default 0)")
    p_email.add_argument("--output", "-o", default="/tmp/opengtm-email-results.json")

    p_pipe = sub.add_parser("pipeline", help="Full pipeline: discover -> research -> qualify -> message -> sync")
    p_pipe.add_argument("--industry", "-i", required=True)
    p_pipe.add_argument("--region", "-r", required=True)
    p_pipe.add_argument("--limit", "-n", type=int, default=10)
    p_pipe.add_argument("--language", choices=["en", "de"], help="Message language (default: en)")
    p_pipe.add_argument("--icp-profile", default="default",
                        choices=["default", "saas", "agency", "professional_services"])
    p_pipe.add_argument("--output", "-o", help="Output JSON path")
    p_pipe.add_argument("--no-sync", action="store_true", help="Skip CRM sync step")
    p_pipe.add_argument("--dry-run", action="store_true", help="Do not write to CRM")

    p_out = sub.add_parser("outreach", help="Manage multi-touch outreach sequences")
    p_out.add_argument("action", choices=["load", "queue", "status"],
                       help="load: add leads | queue: show due today | status: stats")
    p_out.add_argument("--input", help="JSON file with leads (for load action)")
    p_out.add_argument("--state-file", help="Sequence state JSON file path")
    p_out.add_argument("--touch", type=int, choices=[1, 2, 3, 4],
                       help="Filter queue to specific touch number")
    p_out.add_argument("--daily-limit", type=int, default=DEFAULT_DAILY_LIMIT,
                       help=f"Max connection requests per day (default: {DEFAULT_DAILY_LIMIT})")

    p_sync = sub.add_parser("sync", help="Sync leads to Google Sheet CRM via webhook")
    p_sync.add_argument("--input", required=True, help="JSON file with generated leads")
    p_sync.add_argument("--dry-run", action="store_true", help="Print without posting")

    p_ctx = sub.add_parser("context", help="Extract company context from a URL")
    p_ctx.add_argument("--url", "-u", required=True, help="Company website URL")
    p_ctx.add_argument("--output", "-o", help="Output JSON path (default: /tmp/opengtm-context.json)")
    p_ctx.add_argument("--country", help="Target market country (e.g. 'DE', 'US')")
    p_ctx.add_argument("--language", help="Target market language (e.g. 'de', 'en')")
    p_ctx.add_argument("--strict", action="store_true", help="Raise error instead of falling back on API failure")

    p_anl = sub.add_parser("analytics", help="AEO health check (29 checks) + AI visibility")
    p_anl.add_argument("--url", "-u", help="Company website URL")
    p_anl.add_argument("--company", "-c", help="Company name (for mentions check)")
    p_anl.add_argument("--industry", help="Industry (for mentions check)")
    p_anl.add_argument("--health-only", action="store_true", help="Run health check only")
    p_anl.add_argument("--mentions-only", action="store_true", help="Run mentions check only")
    p_anl.add_argument("--output", "-o", help="Output JSON path (default: /tmp/opengtm-analytics.json)")

    p_blog = sub.add_parser("blog", help="Generate a blog article with Gemini + Google Search")
    p_blog.add_argument("--domain", "-d", required=True, help="Company website domain or URL")
    p_blog.add_argument("--keyword", "-k", required=True, help="Primary SEO keyword")
    p_blog.add_argument("--context", help="JSON file with company context (from opengtm context)")
    p_blog.add_argument("--word-count", type=int, default=2000, help="Target word count (default 2000)")
    p_blog.add_argument("--language", default="en", help="Language code (default: en)")
    p_blog.add_argument("--country", default="United States", help="Target country/region")
    p_blog.add_argument("--verify-urls", action="store_true", help="Verify all links in article")
    p_blog.add_argument("--output", "-o", help="Output JSON path (default: /tmp/opengtm-blog.json)")

    p_kw = sub.add_parser("keywords", help="Research SEO keywords (7-stage AI pipeline)")
    p_kw.add_argument("--domain", "-d", required=True, help="Company website domain or URL")
    p_kw.add_argument("--context", help="JSON file with company context (from opengtm context)")
    p_kw.add_argument("--limit", "-n", type=int, default=50, help="Max keywords to return (default 50)")
    p_kw.add_argument("--language", default="en", help="Language code (default: en)")
    p_kw.add_argument("--region", default="US", help="Target region code (default: US)")
    p_kw.add_argument("--min-score", type=int, default=20, help="Min company-fit score 0-100 (default 20)")
    p_kw.add_argument("--clusters", type=int, default=5, help="Number of semantic clusters (default 5)")
    p_kw.add_argument("--no-briefs", action="store_true", help="Skip content brief generation")
    p_kw.add_argument("--output", "-o", help="Output JSON path (default: /tmp/opengtm-keywords.json)")

    p_sm = sub.add_parser("sitemap", help="Crawl and classify sitemap URLs by type")
    p_sm.add_argument("--url", "-u", required=True, help="Company website URL")
    p_sm.add_argument("--validate", action="store_true", help="Validate each URL with HEAD request")
    p_sm.add_argument("--max-urls", type=int, default=500, help="Max URLs to return (default 500)")
    p_sm.add_argument("--output", "-o", help="Output JSON path (default: /tmp/opengtm-sitemap.json)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    dispatch = {
        "discover": cmd_discover,
        "research": cmd_research,
        "qualify": cmd_qualify,
        "message": cmd_message,
        "email": cmd_email,
        "pipeline": cmd_pipeline,
        "outreach": cmd_outreach,
        "sync": cmd_sync,
        "context": cmd_context,
        "analytics": cmd_analytics,
        "blog": cmd_blog,
        "keywords": cmd_keywords,
        "sitemap": cmd_sitemap,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
