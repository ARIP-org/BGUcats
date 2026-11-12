#!/usr/bin/env bash
# Checks, buys and looks at the project's domain name with Route 53's
# registrar, in the organization's management account
# (docs/MANUAL_STEPS.md, step 16).
#
#   aws sso login --profile mgmt-admin --use-device-code
#   infra/scripts/domain.sh contact-template          # what the contact file holds
#   infra/scripts/domain.sh check bgucats.app         # free? what does it cost?
#   infra/scripts/domain.sh buy bgucats.app --max-usd 25
#   infra/scripts/domain.sh status bgucats.app        # the purchase, then the domain
#
# Why the management account and not production:
# - A service control policy never applies to the management account, so
#   nothing has to be opened. route53domains stays denied in the member
#   accounts, where infra/org/scp.tf says it must: it buys in one call.
# - A member account's budget counts everything billed to it. A domain costs
#   about what the $20 line is, and crossing that line freezes every change
#   in that account for the rest of the month (infra/org/budgets.tf). The
#   management account has no such action.
# - A domain outlives accounts. Production has moved account once already.
#
# What it will and will not do:
# - `check` and `status` only look; mgmt-ro is enough for them.
# - `buy` needs mgmt-admin, a price ceiling, and "yes" typed after it has
#   shown the name, the account and today's price. It registers for one
#   year with auto-renew on and every contact hidden from WHOIS.
# - It never prints the contact file and refuses one that is inside the
#   repo: it holds a name, an address and a phone number.
# - A premium name (the registry's own price) is refused by Route 53's API
#   and so by this script.
set -euo pipefail
cd "$(dirname "$0")/../.."

usage() {
  cat >&2 <<'EOF'
usage: infra/scripts/domain.sh contact-template
       infra/scripts/domain.sh check  <name.tld>
       infra/scripts/domain.sh buy    <name.tld> --max-usd <number>
       infra/scripts/domain.sh status <name.tld>
EOF
  exit 1
}

CONTACT="${BGUCATS_DOMAIN_CONTACT:-$HOME/.config/bgucats/domain-contact.json}"
CONTACT_FIELDS="FirstName LastName ContactType AddressLine1 City CountryCode ZipCode PhoneNumber Email"

contact_template() {
  cat <<'EOF'
{
  "FirstName": "",
  "LastName": "",
  "ContactType": "PERSON",
  "AddressLine1": "",
  "City": "",
  "CountryCode": "IL",
  "ZipCode": "",
  "PhoneNumber": "+972.501234567",
  "Email": ""
}
EOF
  cat >&2 <<EOF

Save it OUTSIDE the repo, fill it in, and keep it out of chat:
  mkdir -p "$(dirname "$CONTACT")"
  infra/scripts/domain.sh contact-template > "$CONTACT"
The phone number is +<country code>.<number>, with the dot. The email
address gets a verification link from AWS that must be clicked.
With privacy protection, which this script turns on, none of it is
published.
EOF
}

cmd="${1:-}"
[ -n "$cmd" ] || usage
if [ "$cmd" = contact-template ]; then
  contact_template
  exit 0
fi

domain="${2:-}"
case "$cmd" in check | buy | status) ;; *) usage ;; esac
if ! [[ "$domain" =~ ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.[a-z]{2,24}$ ]]; then
  echo "domain: \"$domain\" is not a name like bgucats.app (lower case, one dot)." >&2
  exit 1
fi
tld="${domain##*.}"

max_usd=""
if [ "$cmd" = buy ]; then
  if [ "${3:-}" != --max-usd ] || ! [[ "${4:-}" =~ ^[0-9]+(\.[0-9]+)?$ ]]; then
    echo "domain: buy needs a ceiling: --max-usd <number>. It refuses a higher price." >&2
    exit 1
  fi
  max_usd="$4"
fi

# --- Which account. The same checks as org-apply.sh.
if [ -n "${AWS_ACCESS_KEY_ID:-}" ]; then
  echo "domain: AWS_ACCESS_KEY_ID is set in this shell, and keys win over any profile." >&2
  echo "  Run: unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN" >&2
  exit 1
fi
export AWS_PROFILE="${AWS_PROFILE:-mgmt-admin}"
case "$AWS_PROFILE" in
  mgmt-admin) ;;
  mgmt-ro)
    if [ "$cmd" = buy ]; then
      echo "domain: $AWS_PROFILE can only look. Buying needs AWS_PROFILE=mgmt-admin." >&2
      exit 1
    fi
    ;;
  *)
    echo "domain: the domain belongs to the management account: AWS_PROFILE must be mgmt-admin or mgmt-ro, not \"$AWS_PROFILE\"." >&2
    exit 1
    ;;
esac
account=$(aws sts get-caller-identity --query Account --output text)
management=$(aws organizations describe-organization --query Organization.MasterAccountId --output text)
if [ "$account" != "$management" ]; then
  echo "domain: profile $AWS_PROFILE is account $account, but the organization's management account is $management." >&2
  exit 1
fi
echo "domain: management account $account, profile $AWS_PROFILE" >&2

# Route 53's registrar has one endpoint, in us-east-1.
r53() { aws route53domains --region us-east-1 "$@"; }

availability() {
  r53 check-domain-availability --domain-name "$domain" --query Availability --output text
}

# "registration renewal currency" for this TLD, e.g. "19.0 19.0 USD".
prices() {
  r53 list-prices --tld "$tld" \
    --query 'Prices[0].[RegistrationPrice.Price, RenewalPrice.Price, RegistrationPrice.Currency]' \
    --output text
}

case "$cmd" in
  check)
    state=$(availability)
    read -r register renew currency <<<"$(prices)"
    echo "$domain: $state"
    echo "first year: $register $currency. each year after: $renew $currency."
    case "$state" in
      AVAILABLE) echo "It can be bought: infra/scripts/domain.sh buy $domain --max-usd <ceiling>" ;;
      DONT_KNOW) echo "The registry did not answer. Try again in a minute." ;;
      *) echo "It cannot be bought here as it is. Try another name." ;;
    esac
    ;;

  buy)
    if [ ! -f "$CONTACT" ]; then
      echo "domain: no contact file at $CONTACT. Make one: infra/scripts/domain.sh contact-template" >&2
      exit 1
    fi
    contact_real=$(realpath "$CONTACT")
    repo_real=$(realpath .)
    case "$contact_real/" in
      "$repo_real"/*)
        echo "domain: the contact file is inside the repo ($contact_real). Move it out: it holds an address and a phone number." >&2
        exit 1
        ;;
    esac
    for field in $CONTACT_FIELDS; do
      if [ -z "$(jq -r --arg f "$field" '.[$f] // "" | tostring' "$contact_real")" ]; then
        echo "domain: the contact file has no $field." >&2
        exit 1
      fi
    done
    if ! [[ "$(jq -r .PhoneNumber "$contact_real")" =~ ^\+[0-9]{1,3}\.[0-9]{4,26}$ ]]; then
      echo "domain: PhoneNumber must look like +972.501234567 (country code, a dot, the number)." >&2
      exit 1
    fi

    state=$(availability)
    if [ "$state" != AVAILABLE ]; then
      echo "domain: $domain is $state, not AVAILABLE. Nothing bought." >&2
      exit 1
    fi
    read -r register renew currency <<<"$(prices)"
    if [ "$currency" != USD ]; then
      echo "domain: the price came back in \"$currency\", not USD. Nothing bought." >&2
      exit 1
    fi
    if ! awk -v p="$register" -v m="$max_usd" 'BEGIN { exit !(p + 0 > 0 && p + 0 <= m + 0) }'; then
      echo "domain: $domain costs $register USD, over the ceiling of $max_usd. Nothing bought." >&2
      exit 1
    fi

    cat <<EOF

About to buy, in account $account:
  name         $domain
  now          $register USD for one year. No refund should be expected.
  every year   $renew USD, charged automatically (auto-renew on)
  contact      from $contact_real (not shown), hidden from WHOIS
  also         Route 53 makes a hosted zone for it: 0.50 USD a month

EOF
    read -r -p 'Type "yes" to buy: ' answer || answer=""
    if [ "$answer" != yes ]; then
      echo "Nothing bought."
      exit 1
    fi

    operation=$(r53 register-domain \
      --domain-name "$domain" \
      --duration-in-years 1 \
      --auto-renew \
      --admin-contact "file://$contact_real" \
      --registrant-contact "file://$contact_real" \
      --tech-contact "file://$contact_real" \
      --privacy-protect-admin-contact \
      --privacy-protect-registrant-contact \
      --privacy-protect-tech-contact \
      --query OperationId --output text)
    cat <<EOF
Requested. Operation $operation.
Next:
  1. AWS emails the contact's address a verification link. Click it within
     15 days, or the domain is suspended.
  2. In a few minutes to a few hours: infra/scripts/domain.sh status $domain
EOF
    ;;

  status)
    echo "== requests for $domain"
    r53 list-operations \
      --query "Operations[?DomainName=='$domain'].[SubmittedDate, Type, Status, Message]" \
      --output table
    echo "== the domain"
    # Only fields that are not about a person.
    if ! r53 get-domain-detail --domain-name "$domain" \
      --query '{expires: ExpirationDate, autoRenew: AutoRenew, nameservers: Nameservers[].Name, status: StatusList, privacy: RegistrantPrivacy}' \
      --output json 2>/dev/null; then
      echo "Not registered in this account (yet). A new registration shows here when its request is SUCCESSFUL."
    fi
    ;;
esac
