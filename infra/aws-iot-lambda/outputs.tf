output "lambda_name" {
  value = aws_lambda_function.respiration_handler.function_name
}

output "lambda_arn" {
  value = aws_lambda_function.respiration_handler.arn
}

output "iot_rule_name" {
  value = aws_iot_topic_rule.respiration_rule.name
}

output "iot_rule_arn" {
  value = aws_iot_topic_rule.respiration_rule.arn
}
