# Todo Design

## TodoItem Schema

TodoItem 记录：

- `id`
- `title`
- `description`
- `status`
- `priority`
- `dependencies`
- `assigned_tool`
- `inputs`
- `outputs`
- `error`
- `react_steps`
- `created_at`
- `updated_at`

## Todo Status

支持以下状态：

- `pending`
- `in_progress`
- `completed`
- `completed_with_warning`
- `failed`
- `blocked`
- `skipped`
- `cancelled`

## Dependencies

Todo 之间通过 `dependencies` 建立执行约束：

- 前置 todo 完成后，下一个 todo 才 ready
- 反射器可以在运行时追加依赖
- 某些 blocked todo 会在依赖满足后重新转回 pending

## Todo and Trace

每次状态变化都写 trace：

- `TodoCreated`
- `TodoStarted`
- `TodoCompleted`
- `TodoCompletedWithWarning`
- `TodoFailed`
- `TodoSkipped`
- `TodoBlocked`
- `TodoCancelled`

这让 todo 不只是 UI 可视化对象，也是调试证据。

## Todo and AgentState

`AgentState.todos` 保存完整 todo 列表，`current_todo_id` 保存当前执行位置。这样：

- `state.json` 可以恢复任务
- `summary.md` 可以回放执行摘要
- 失败时仍然保留中间执行结构

## Todo and ReAct

每个 todo 都维护 `react_steps`：

- why
- tool action
- observation
- next decision

也就是说，Todo 是外层结构，ReAct step 是内层思考轨迹。

