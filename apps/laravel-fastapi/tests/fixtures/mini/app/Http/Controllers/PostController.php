<?php

namespace App\Http\Controllers;

use App\Http\Requests\StorePostRequest;
use App\Http\Resources\PostResource;
use App\Models\Post;
use Illuminate\Support\Facades\DB;

class PostController extends Controller
{
    public function index()
    {
        return PostResource::collection(Post::latest()->get());
    }

    public function store(StorePostRequest $request)
    {
        $post = Post::create($request->validated());

        return new PostResource($post);
    }

    public function show(int $id)
    {
        return new PostResource(Post::findOrFail($id));
    }

    public function destroy(int $id)
    {
        Post::findOrFail($id)->delete();

        return response()->noContent();
    }

    public function relatorio()
    {
        $total = DB::select(DB::raw('select count(*) as n from posts'));
        event('relatorio.gerado');
        dispatch(new \App\Jobs\Recalcular());

        return algo_desconhecido($total);
    }
}
