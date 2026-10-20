<?php

use App\Http\Controllers\PostController;
use Illuminate\Support\Facades\Route;

Route::get('posts', [PostController::class, 'index']);
Route::post('posts', [PostController::class, 'store']);
Route::get('posts/{id}', [PostController::class, 'show']);
Route::delete('posts/{id}', [PostController::class, 'destroy']);
Route::get('relatorio', [PostController::class, 'relatorio']);
Route::get('ping', function () {
    return 'pong';
});
