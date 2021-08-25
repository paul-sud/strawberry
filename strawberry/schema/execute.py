from asyncio import ensure_future
from inspect import isawaitable
from typing import Any, Awaitable, List, Optional, Sequence, Tuple, Type, cast

from graphql import (
    ExecutionContext as GraphQLExecutionContext,
    ExecutionResult as GraphQLExecutionResult,
    GraphQLError,
    GraphQLSchema,
    execute as original_execute,
    parse,
)
from graphql.language import DocumentNode
from graphql.validation import ASTValidationRule, validate

from strawberry.extensions import Extension
from strawberry.extensions.runner import ExtensionsRunner
from strawberry.types import ExecutionContext, ExecutionResult


def parse_document(execution_context: ExecutionContext, query: str) -> DocumentNode:
    if execution_context.graphql_document:
        return execution_context.graphql_document

    document = parse(query)
    execution_context.graphql_document = document
    return document


def validate_document(
    schema: GraphQLSchema,
    document: DocumentNode,
    validation_rules: Tuple[Type[ASTValidationRule], ...],
) -> List[GraphQLError]:
    validation_errors = validate(
        schema,
        document,
        validation_rules,
    )
    return validation_errors


async def execute(
    schema: GraphQLSchema,
    query: str,
    extensions: Sequence[Type[Extension]],
    execution_context: ExecutionContext,
    additional_middlewares: List[Any] = None,
    execution_context_class: Optional[Type[GraphQLExecutionContext]] = None,
    validate_queries: bool = True,
) -> ExecutionResult:
    extensions_runner = ExtensionsRunner(
        execution_context=execution_context,
        extensions=[
            extension(execution_context=execution_context) for extension in extensions
        ],
    )

    additional_middlewares = additional_middlewares or []

    async with extensions_runner.request():
        # Note: In graphql-core the schema would be validated here but in
        # Strawberry we are validating it at initialisation time instead

        try:
            async with extensions_runner.parsing():
                document = parse_document(execution_context, query)
        except GraphQLError as error:
            execution_context.errors = [error]
            return ExecutionResult(
                data=None,
                errors=[error],
                extensions=await extensions_runner.get_extensions_results(),
            )

        except Exception as error:  # pragma: no cover
            error = GraphQLError(str(error), original_error=error)

            execution_context.errors = [error]
            return ExecutionResult(
                data=None,
                errors=[error],
                extensions=await extensions_runner.get_extensions_results(),
            )

        if validate_queries:
            async with extensions_runner.validation():
                # Validation has already been run
                if execution_context.errors is None:
                    assert execution_context.graphql_schema
                    assert execution_context.graphql_document
                    execution_context.errors = validate_document(
                        execution_context.graphql_schema,
                        execution_context.graphql_document,
                        execution_context.validation_rules,
                    )

                if execution_context.errors:
                    return ExecutionResult(data=None, errors=execution_context.errors)

        result = original_execute(
            schema,
            document,
            root_value=execution_context.root_value,
            middleware=extensions_runner.as_middleware_manager(*additional_middlewares),
            variable_values=execution_context.variables,
            operation_name=execution_context.operation_name,
            context_value=execution_context.context,
            execution_context_class=execution_context_class,
        )

        if isawaitable(result):
            result = await cast(Awaitable[GraphQLExecutionResult], result)

        execution_context.result = cast(GraphQLExecutionResult, result)

    result = cast(GraphQLExecutionResult, result)

    return ExecutionResult(
        data=result.data,
        errors=result.errors,
        extensions=await extensions_runner.get_extensions_results(),
    )


def execute_sync(
    schema: GraphQLSchema,
    query: str,
    extensions: Sequence[Type[Extension]],
    execution_context: ExecutionContext,
    additional_middlewares: List[Any] = None,
    execution_context_class: Optional[Type[GraphQLExecutionContext]] = None,
    validate_queries: bool = True,
) -> ExecutionResult:
    extensions_runner = ExtensionsRunner(
        execution_context=execution_context,
        extensions=[
            extension(execution_context=execution_context) for extension in extensions
        ],
    )

    additional_middlewares = additional_middlewares or []

    with extensions_runner.request():
        # Note: In graphql-core the schema would be validated here but in
        # Strawberry we are validating it at initialisation time instead

        try:
            with extensions_runner.parsing():
                document = parse_document(execution_context, query)
        except GraphQLError as error:
            execution_context.errors = [error]
            return ExecutionResult(
                data=None,
                errors=[error],
                extensions=extensions_runner.get_extensions_results_sync(),
            )

        except Exception as error:  # pragma: no cover
            error = GraphQLError(str(error), original_error=error)

            execution_context.errors = [error]
            return ExecutionResult(
                data=None,
                errors=[error],
                extensions=extensions_runner.get_extensions_results_sync(),
            )

        if validate_queries:
            with extensions_runner.validation():
                # Validation has already been run
                if execution_context.errors is None:
                    assert execution_context.graphql_schema
                    assert execution_context.graphql_document
                    execution_context.errors = validate_document(
                        execution_context.graphql_schema,
                        execution_context.graphql_document,
                        execution_context.validation_rules,
                    )

                if execution_context.errors:
                    return ExecutionResult(data=None, errors=execution_context.errors)

        result = original_execute(
            schema,
            document,
            root_value=execution_context.root_value,
            middleware=extensions_runner.as_middleware_manager(*additional_middlewares),
            variable_values=execution_context.variables,
            operation_name=execution_context.operation_name,
            context_value=execution_context.context,
            execution_context_class=execution_context_class,
        )

        if isawaitable(result):
            ensure_future(cast(Awaitable[GraphQLExecutionResult], result)).cancel()
            raise RuntimeError("GraphQL execution failed to complete synchronously.")

        result = cast(GraphQLExecutionResult, result)
        execution_context.result = result
        if result.errors:
            execution_context.errors = result.errors

    return ExecutionResult(
        data=result.data,
        errors=result.errors,
        extensions=extensions_runner.get_extensions_results_sync(),
    )
