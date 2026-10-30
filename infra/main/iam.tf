# Every role in this root carries the boundary infra/bootstrap creates
# (bootstrap/lambda_boundary.tf). It caps what any role here can do, however
# its own policy is written, and the deploy role is only allowed to create or
# edit roles that carry it. A new aws_iam_role without this line fails to
# deploy with AccessDenied on iam:CreateRole.
#
# Built from the name rather than read from bootstrap's outputs: the two
# roots share no state, the same reason bootstrap writes out our names.
locals {
  lambda_permissions_boundary = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:policy/bgucats-lambda-permissions-boundary"
}
