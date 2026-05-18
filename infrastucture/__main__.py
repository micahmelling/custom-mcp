import pulumi
import pulumi_aws as aws
import pulumi_docker as docker
from pulumi import ResourceOptions


def main(
        project_name,
        environment,
        aws_region,
        ingress_cidr_blocks,
        cpu,
        memory,
        task_count,
        domain_name,
        hosted_zone_id,
        certificate_arn,
        env_vars,
        app_port,
        container_port,
        health_check_port,
        container_name,
        health_check_path,
        vpc_id,
        alb_subnet_ids,
        ecs_subnet_ids,
        ecs_policies_to_create,
        ecs_policies_to_attach,
        role_arn,
    ):
    project_name = f"{project_name}_{environment}"

    # pulumi plugin install resource docker
    # pip install pulumi_aws pulumi_docker
    app_repo = aws.ecr.Repository(project_name)
    auth_token = aws.ecr.get_authorization_token_output(registry_id=app_repo.registry_id)
    app_image = docker.Image(project_name,
                             build=docker.DockerBuildArgs(
                                 context="../app",
                                 platform='linux/amd64',
                             ),
                             image_name=app_repo.repository_url.apply(lambda url: f"{url}:latest"),
                             registry=docker.RegistryArgs(
                                 server=app_repo.repository_url,
                                 username=auth_token.user_name,
                                 password=auth_token.password,
                             )
                             )

    ecs_role = aws.iam.Role(
        project_name,
        name=project_name,
        assume_role_policy="""{
          "Version": "2012-10-17",
          "Statement": [
            {
              "Action": "sts:AssumeRole",
              "Principal": {
                "Service": "ecs-tasks.amazonaws.com"
              },
              "Effect": "Allow",
              "Sid": ""
            }
          ]
        }
        """
    )

    policy_arns = []
    for policy in ecs_policies_to_create:
        iam_policy = aws.iam.Policy(
            policy[0],
            name=policy[0],
            policy=policy[1]
        )
        policy_arns.append(iam_policy.arn)

    for index, policy_arn in enumerate(policy_arns + ecs_policies_to_attach):
        attach = aws.iam.RolePolicyAttachment(
            f'attached_{index}_{environment}',
            role=ecs_role.name,
            policy_arn=policy_arn
        )

    ecs_cluster = aws.ecs.Cluster(
        project_name,
        name=project_name,
        settings=[
            aws.ecs.ClusterSettingArgs(
                name='containerInsights',
                value='enabled'
            )
        ]
    )

    alb_security_group = aws.ec2.SecurityGroup(f"{project_name}_alb_sec_grp",
                                               name=f"{project_name}_alb_sec_grp",
                                               vpc_id=vpc_id,
                                               description='Enable HTTPS access',
                                               ingress=[aws.ec2.SecurityGroupIngressArgs(
                                                   protocol='tcp',
                                                   from_port=app_port,
                                                   to_port=app_port,
                                                   cidr_blocks=ingress_cidr_blocks
                                               )],
                                               egress=[aws.ec2.SecurityGroupEgressArgs(
                                                   protocol='-1',
                                                   from_port=0,
                                                   to_port=0,
                                                   cidr_blocks=['0.0.0.0/0'],
                                               )],
                                               )

    ecs_security_group = aws.ec2.SecurityGroup(f"{project_name}_ecs_sec_grp",
                                               name=f"{project_name}_ecs_sec_grp",
                                               vpc_id=vpc_id,
                                               description='Enable ALB Access',
                                               ingress=[
                                                   aws.ec2.SecurityGroupIngressArgs(
                                                       protocol='tcp',
                                                       from_port=container_port,
                                                       to_port=container_port,
                                                       security_groups=[alb_security_group.id]
                                                   )
                                               ],
                                               egress=[aws.ec2.SecurityGroupEgressArgs(
                                                   protocol='-1',
                                                   from_port=0,
                                                   to_port=0,
                                                   cidr_blocks=['0.0.0.0/0'],
                                               )],
                                               )

    load_balancer = aws.lb.LoadBalancer(project_name,
                                        name=project_name.replace('_', ''),
                                        security_groups=[alb_security_group.id],
                                        subnets=alb_subnet_ids,
                                        )

    target_group = aws.lb.TargetGroup(project_name,
                                      name=project_name.replace('_', ''),
                                      port=container_port,
                                      protocol='HTTP',
                                      target_type='ip',
                                      vpc_id=vpc_id,
                                      health_check={
                                          "path": f"{health_check_path}",
                                          "port": f"{health_check_port}",
                                          "protocol": "HTTP",
                                          "interval": 15
                                      }
                                      )

    listener = aws.lb.Listener(project_name,
                               load_balancer_arn=load_balancer.arn,
                               port=app_port,
                               protocol='HTTPS',
                               ssl_policy='ELBSecurityPolicy-TLS13-1-2-Res-2021-06',
                               certificate_arn=certificate_arn,
                               default_actions=[aws.lb.ListenerDefaultActionArgs(
                                   type='forward',
                                   target_group_arn=target_group.arn,
                               )],
                               )

    route_53_record = aws.route53.Record(domain_name,
                                         zone_id=hosted_zone_id,
                                         name=domain_name,
                                         type="A",
                                         aliases=[aws.route53.RecordAliasArgs(
                                             name=load_balancer.dns_name,
                                             zone_id=load_balancer.zone_id,
                                             evaluate_target_health=False,
                                         )]
                                         )

    ecs_log_group = aws.cloudwatch.LogGroup(f'ecs/{project_name}', name=f'ecs/{project_name}')

    task_definition = aws.ecs.TaskDefinition(project_name,
                                             family=project_name,
                                             cpu=cpu,
                                             memory=memory,
                                             network_mode='awsvpc',
                                             requires_compatibilities=['FARGATE'],
                                             execution_role_arn=role_arn,
                                             task_role_arn=ecs_role.arn,
                                             container_definitions=pulumi.Output.json_dumps([{
                                                 'name': container_name,
                                                 'image': app_image.image_name,
                                                 'portMappings': [{
                                                     'containerPort': container_port,
                                                     'protocol': 'tcp'
                                                 }],
                                                 "environment": env_vars,
                                                 "logConfiguration": {
                                                     "logDriver": "awslogs",
                                                     "options": {
                                                         "awslogs-group": f'ecs/{project_name}',
                                                         "awslogs-region": aws_region,
                                                         "awslogs-stream-prefix": "container-"
                                                     }
                                                 }
                                             }])
                                             )

    ecs_service = aws.ecs.Service(project_name,
                                  cluster=ecs_cluster.arn,
                                  desired_count=task_count,
                                  launch_type='FARGATE',
                                  task_definition=task_definition.arn,
                                  network_configuration=aws.ecs.ServiceNetworkConfigurationArgs(
                                      assign_public_ip=True,
                                      subnets=ecs_subnet_ids,
                                      security_groups=[ecs_security_group.id],
                                  ),
                                  load_balancers=[aws.ecs.ServiceLoadBalancerArgs(
                                      target_group_arn=target_group.arn,
                                      container_name=container_name,
                                      container_port=container_port,
                                  )],
                                  opts=ResourceOptions(depends_on=[listener]),
                                  )


if __name__ == "__main__":
    main(
        project_name='mcp',
        environment='stage',
        aws_region='us-east-1',
        ingress_cidr_blocks=[''],
        cpu='256',
        memory='1GB',
        task_count=1,
        domain_name='',
        hosted_zone_id='',
        certificate_arn='',
        env_vars=[
        {
            "name": "ENVIRONMENT",
            "value": "stage"
        }
        ],
        app_port=443,
        container_port=8000,
        health_check_port=8000,
        container_name='mcp',
        health_check_path='/health',
        vpc_id='',
        alb_subnet_ids=[],
        ecs_subnet_ids=[],
        ecs_policies_to_create=[],
        ecs_policies_to_attach=[],
        role_arn='',
    )
